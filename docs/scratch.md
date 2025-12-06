cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env # Then edit with your Spotify credentials
alembic upgrade head
uvicorn app.main:app --reload
