# Backend-Shivalik

Installation
Clone the repository:
git clone https://github.com/swciitg/backend-shivalik.git
cd  backend-shivalik
Create a virtual environment:
python -m venv venv
Activate the virtual environment:

Windows

venv\Scripts\activate

Linux / macOS

source venv/bin/activate
Install dependencies:
pip install -r requirements.txt
Create a .env file using .env.example and configure the required environment variables.
Apply migrations:
python manage.py migrate
Start the development server:
python manage.py runserver

The backend will be available at:

http://127.0.0.1:8000/
Project Structure
backend/
├── api/
├── config/
├── manage.py
├── requirements.txt
├── .env.example
└── README.md
Useful Commands

Run the development server:

python manage.py runserver

Create migrations:

python manage.py makemigrations

Apply migrations:

python manage.py migrate

Create a superuser:

python manage.py createsuperuser