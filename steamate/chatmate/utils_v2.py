# from langchain.prompts import ChatPromptTemplate
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_core.runnables import RunnableLambda
from langchain.schema import Document
from langchain_community.document_loaders import CSVLoader
from dotenv import load_dotenv
from langchain_community.vectorstores import PGVector # pgvector용 모듈
import os
import pandas as pd
from .models import ChatSession, ChatMessage
from langchain.schema import HumanMessage, AIMessage
from cachetools import TTLCache


load_dotenv()

# API 키 환경변수에서 가져오기
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

# PostgreSQL 연결 문자열 (환경 변수에서 가져오거나 직접 설정)
CONNECTION_STRING = os.getenv('DATABASE_URL')  # 예: "postgresql://user:password@localhost:5432/dbname"

# 챗봇 모델 설정
chat = ChatOpenAI(model="gpt-4o-mini", api_key=OPENAI_API_KEY)

# 임베딩 모델 설정
embeddings = OpenAIEmbeddings(
    model="text-embedding-3-small",
)

# 파서
str_outputparser = StrOutputParser()

# 템플릿
prompt = ChatPromptTemplate.from_messages([
    MessagesPlaceholder(variable_name="chat_history"),
    (
        "system",
        """당신은 게임 추천 전문가입니다. 반드시 다음 규칙을 따르세요:

        1. 가장 중요한 규칙:
        - 반드시 아래 '추천 가능 게임 목록'에 포함된 게임만 추천해야 합니다
        - 목록에 없는 게임은 절대 언급하지 마세요
        
        2. 사용자 정보:
        - 선호하는 장르: {genre}
        - 이전에 플레이하고 좋아했던 게임: {game}
        
        3. 추천 가능 게임 목록 (이 목록의 게임만 추천 가능):
        {context}
        
        4. 추천 방식:
        - 위 '추천 가능 게임 목록'에서 3개의 게임만 선택하여 추천
        - 각 게임에 대해 다음을 고려하여 추천 이유를 작성:
          * 사용자의 선호 장르와의 연관성
          * 이전에 플레이한 게임과의 유사점
          * 게임의 핵심 특징
        
        5. 답변 형식:
        [추천 게임 1]
        - 추천 이유 및 설명
        
        [추천 게임 2]
        - 추천 이유 및 설명
        
        [추천 게임 3]
        - 추천 이유 및 설명
        
        주의: 반드시 위 '추천 가능 게임 목록'에 없는 게임을 언급하지 마세요.
        """,
    ),
    ("human", "{input}"),
])
# 데이터 불러오기
def load_and_chunk_csv(chunk_size=100):
    file_path = os.path.abspath('chatmate/data/games_v3.csv')
    data = pd.read_csv(file_path, encoding="utf-8")
    
    chunks = []
    for i in range(0, len(data), chunk_size):
        chunk = data.iloc[i:i+chunk_size]
        chunk_documents = [
            Document(
                page_content=" | ".join([f"{col}: {value}" for col, value in row.items() if col != "appid"]),
                metadata={"appid": row["appid"], "genres": row["genres"]}
            )
            for _, row in chunk.iterrows()
        ]
        chunks.append(chunk_documents)
    
    return chunks

# 벡터 스토어 생성
def create_vectorstore_from_chunks(chunks):
    vector_store = None
    for chunk in chunks:
        if vector_store is None:
            vector_store = PGVector.from_documents(
                documents=chunk,
                embedding=embeddings,
                connection_string=CONNECTION_STRING,
                collection_name="games_collection",
                use_jsonb=True
            )
        else:
            vector_store.add_documents(chunk)
    
    return vector_store


# 벡터 스토어 초기화
def initialize_vectorstore():
    
    try: 
        # 벡터 스토어 로드 시도
        vector_store = PGVector(
            embedding_function=embeddings,
            connection_string=CONNECTION_STRING,
            collection_name="games_collection",
            use_jsonb=True
        )
        # 우선 모든에러처리
    except Exception as e: 
        print(f"벡터 db 초기화 중 오류 :: {e}")
    
    # 데이터 비어있는지 확인
    sample = vector_store.similarity_search("test", k=1)
    if not sample:
        print("PGVector 벡터 DB가 비어 있습니다. 데이터를 생성합니다.")
        data = load_and_chunk_csv()
        vector_store = create_vectorstore_from_chunks(data)
    else:
        print("기존 PGVector 벡터 DB를 로드했습니다.")
    
    return vector_store
# 벡터 스토어 초기화
vector_store = initialize_vectorstore()

def docs_join_logic(docs):
    return "\n".join([doc.page_content for doc in docs])

# 가져온 문서 붙이기
docs_join = RunnableLambda(docs_join_logic)

# 체인
chain = prompt | chat | str_outputparser

# store를 TTLCache로 변경 (maxsize=1000개, ttl=1800초(30분))
store = TTLCache(maxsize=1000, ttl=1800)

# RDB에 있는 대화 내역을 메모리에 저장하는 함수
def bring_session_history(session_id):
    try:
        # 세션이 없거나 만료되었으면 새로 생성
        if session_id not in store:
            history = ChatMessageHistory()
            for message in ChatMessage.objects.filter(session_id=session_id).order_by('created_at')[:5]:
                history.add_message(HumanMessage(content=message.user_message))
                history.add_message(AIMessage(content=message.chatbot_message))
            store[session_id] = history
        return store[session_id]
    except Exception as e:
        print(f"Session {session_id} expired or error occurred: {e}")
        return None

def delete_messages_from_history(session_id, user_message):
    """
    채팅 히스토리에서 특정 메시지와 그에 대한 AI 응답을 삭제합니다.
    """
    try:
        session_history = store.get(session_id)
        if not session_history:
            print(f"세션 {session_id}의 히스토리를 찾을 수 없습니다.")
            return False
            
        # HumanMessage의 content로 인덱스 찾기
        for i, msg in enumerate(session_history.messages):
            if (isinstance(msg, HumanMessage) and 
                msg.content == user_message):
                # 해당 메시지와 다음 AI 메시지 삭제
                del session_history.messages[i:i+2]
                return True
                
        return False
        
    except Exception as e:
        print(f"메시지 삭제 중 오류 발생: {e}")
        return False
    
# 세션 내역 가져오기
def get_session_history(session_ids):
    if session_ids not in store:
        store[session_ids] = ChatMessageHistory()
    return store[session_ids]

# 체인을 묶어 기억해줄 객체
chain_with_history = RunnableWithMessageHistory(
    chain,
    get_session_history,
    input_messages_key="input",
    history_messages_key="chat_history",
)

def generate_pseudo_document(user_input, chat):
    """Query2doc/HyDE approach to generate a pseudo document."""
    pseudo_doc_prompt = ChatPromptTemplate.from_messages([
        ("system", """
        Generate an ideal game description document based on the user's gaming query.
        The document must include the following elements:
        - Game genre and style
        - Core gameplay elements
        - Atmosphere and theme
        - Expected gaming experience
        """),
        ("human", "{input}")
    ])
    
    pseudo_doc_chain = pseudo_doc_prompt | chat | str_outputparser
    return pseudo_doc_chain.invoke({"input": user_input})

def decompose_query(pseudo_doc, chat):
    """Decompose the pseudo document into sub-queries."""
    decompose_prompt = ChatPromptTemplate.from_messages([
        ("system", """
        Break down the given game description document into specific sub-queries.
        Consider aspects such as:
        - Genre-related questions
        - Gameplay mechanics questions
        - Story/atmosphere questions
        - Difficulty/accessibility questions
        """),
        ("human", "{input}")
    ])
    
    decompose_chain = decompose_prompt | chat | str_outputparser
    return decompose_chain.invoke({"input": pseudo_doc}).split('\n')

def chatbot_call(user_input, session_id, genre, game, appid):
    # 1. Generate pseudo document
    pseudo_doc = generate_pseudo_document(user_input, chat)
    
    # 2. Decompose the generated pseudo document into sub-queries
    sub_queries = decompose_query(pseudo_doc, chat)
    
    # 3. Perform search for each sub-query
    all_contexts = []
    
    # 필터 조건 생성
    filter_conditions = []
    
    if genre:  # 장르가 있을 때만 필터 추가
        filter_conditions.append({"genres": {"$in": genre}})
    if appid:  # appid가 있을 때만 필터 추가
        filter_conditions.append({"appid": {"$nin": appid}})
        
    # 검색 파라미터 설정
    search_kwargs = {"k": 3}
    if filter_conditions:  # 필터 조건이 하나라도 있을 때만 필터 추가
        search_kwargs["filter"] = {"$and": filter_conditions}
        
    retriever = vector_store.as_retriever(search_kwargs=search_kwargs)
    
    # Search based on pseudo document
    pseudo_doc_results = retriever.invoke(pseudo_doc)
    all_contexts.extend(pseudo_doc_results)
    
    # Search based on sub-queries
    for sub_query in sub_queries:
        sub_results = retriever.invoke(sub_query)
        all_contexts.extend(sub_results)
    
    # 4. 검색 결과 통합 및 중복 제거 (page_content 한 번만 접근)
    context = "\n".join({doc.page_content for doc in all_contexts})
    
    # 5. Generate final response
    answer = chain_with_history.invoke(
        {
            "input": user_input,
            "context": context,
            "genre": ", ".join(genre),
            "game": ", ".join(game)
        },
        config={"configurable": {"session_id": session_id}}
    )
    print(context)
    return answer