import os
import pandas as pd
from datetime import datetime
from django.core.management.base import BaseCommand
from django.db.utils import IntegrityError
from account.models import Game, Genre
from dotenv import load_dotenv

load_dotenv()
STEAM_API_KEY = os.getenv("STEAM_API_KEY")

class Command(BaseCommand):
    """
    python manage.py load_data 명령어로 csv 파일에 정제된 데이터를 데이터베이스에 저장
    """
    help = "Load game data from a CSV file into the database"

    def handle(self, *args, **kwargs):
        file_path = os.path.join("account", "data", "steam_game_details.csv")

        if not os.path.exists(file_path):
            self.stdout.write(self.style.ERROR(f"File not found: {file_path}"))
            return

        # pandas로 CSV 데이터 로드 및 NaN 처리
        df = pd.read_csv(file_path, encoding="utf-8-sig").fillna({
            "release_date": "",
            "description": "",
            "review_score": 0
        })

        game_count = 0
        genre_count = 0  # 장르 개수 추적

        for _, row in df.iterrows():
            try:
                # 필수 값 처리
                appid = int(row["appid"])
                title = row["name"].strip() if row["name"] else "Unknown"
                genre_names = row["genres"].split(",") if row["genres"] else []
                released_at = row["release_date"]
                description = row["detailed_description"]
                review_score = float(row["positive_ratings"]) if row["positive_ratings"] else 0

                # 날짜 변환 (DD MMM, YYYY → YYYY-MM-DD)
                try:
                    released_at = datetime.strptime(released_at, "%d %b, %Y").date()
                except (ValueError, TypeError):
                    released_at = None

                # 게임 저장 (중복 체크 + 신규 생성 가능)
                game, created = Game.objects.get_or_create(
                    appid=appid,
                    defaults={
                        "title": title,
                        "released_at": released_at,
                        "description": description,
                        "review_score": review_score,
                    }
                )

                # 장르 추가 (새로운 장르가 생성된 경우만 카운트)
                for genre_name in genre_names:
                    genre, created_genre = Genre.objects.get_or_create(genre_name=genre_name.strip())
                    if created_genre:
                        genre_count += 1  # 새롭게 생성된 장르만 카운트

                game_count += 1

            except IntegrityError:
                self.stdout.write(self.style.WARNING(f"Duplicate entry skipped for appid {appid}"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error processing row {row.to_dict()} -> {e}"))

        self.stdout.write(self.style.SUCCESS(f"Successfully added {game_count} new games!"))
        self.stdout.write(self.style.SUCCESS(f"Successfully added {genre_count} new genres!"))  # 정확한 장르 개수 출력
