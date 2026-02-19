"""
One-time script to fix migration inconsistency when switching to a custom User model.
Directly records users.0001_initial in django_migrations so Django no longer sees
an inconsistency with admin.0001_initial being applied before it.

Run with: pipenv run python fix_migrations.py
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ikigembe_bn.settings')
django.setup()

from django.db import connection
from django.utils.timezone import now

with connection.cursor() as cursor:
    # Check what's already recorded
    cursor.execute("SELECT app, name FROM django_migrations ORDER BY app, id;")
    rows = cursor.fetchall()
    print("Current django_migrations entries:")
    for row in rows:
        print(f"  {row[0]}.{row[1]}")

    # Check if users.0001_initial is already recorded
    cursor.execute(
        "SELECT COUNT(*) FROM django_migrations WHERE app = %s AND name = %s;",
        ['users', '0001_initial']
    )
    count = cursor.fetchone()[0]

    if count == 0:
        cursor.execute(
            "INSERT INTO django_migrations (app, name, applied) VALUES (%s, %s, %s);",
            ['users', '0001_initial', now()]
        )
        print("\n✅ Inserted users.0001_initial into django_migrations (fake).")
    else:
        print("\nℹ️  users.0001_initial already recorded — nothing to do.")

print("\nDone. Now run: pipenv run python manage.py migrate")
