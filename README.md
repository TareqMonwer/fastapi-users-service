## Installation
`pip install -r requirements.txt`

## Setup
Setup .env file with DATABASE_URL env variable in project root.
ie: `postgresql://user:password@myhost:5432/mydb`

## Migration
1. After model changes, use: `alembic revision --autogenerate -m <your message>`
2. Once migration file is ready, use: `alembic upgrade head`

## Test


## Run
