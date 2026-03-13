# filepath: render.yaml
services:
  - type: web
    name: ikigembe-backend
    envVars:
      - key: DATABASE_URL
        fromDatabase:
          name: ikigembe-db
          property: connectionString
      - key: SECRET_KEY
        generateValue: true
      - key: DEBUG
        value: false
      # Add other env vars as needed
    buildCommand: pip install -r requirements.txt
    startCommand: python manage.py migrate && python manage.py runserver 0.0.0.0:8000
  - type: pserv
    name: ikigembe-db
    env: postgres