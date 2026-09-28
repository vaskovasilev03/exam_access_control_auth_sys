import os
import boto3
from botocore.exceptions import NoCredentialsError, ClientError

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT")
MINIO_ACCESS_KEY = os.getenv("MINIO_ROOT_USER")
MINIO_SECRET_KEY = os.getenv("MINIO_ROOT_PASSWORD")
BUCKET_NAME = os.getenv("MINIO_BUCKET_NAME")

s3_client = boto3.client(
    "s3",
    endpoint_url=MINIO_ENDPOINT,
    aws_access_key_id=MINIO_ACCESS_KEY,
    aws_secret_access_key=MINIO_SECRET_KEY,
    region_name="eu-central-1"
)

def init_storage():
    """ Автоматично създава кофата в MinIO при стартиране, ако не съществува """
    try:
        s3_client.head_bucket(Bucket=BUCKET_NAME)
        print(f"Cloud bucket '{BUCKET_NAME}' already exists in MinIO.")
    except ClientError as e:
        # Грешка 404 означава, че кофата не съществува и трябва да я създадем
        error_code = e.response['Error']['Code']
        if error_code == '404':
            s3_client.create_bucket(Bucket=BUCKET_NAME)
            print(f"Successfully created bucket '{BUCKET_NAME}' in MinIO!")
        else:
            print(f"Error initializing MinIO: {e}")

def upload_photo_to_cloud(file_data, object_name: str, content_type: str) -> str:
    """ Качва файл директно в MinIO облака и връща неговия вътрешен път """
    try:
        # Качваме бинарните данни на файла
        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=object_name,
            Body=file_data,
            ContentType=content_type
        )
        # Връщаме виртуалния път, който ще запишем в Postgres (photo_path)
        return f"/{BUCKET_NAME}/{object_name}"
    except Exception as e:
        print(f"Error uploading to MinIO: {e}")
        raise e

def get_photo_from_cloud(object_name: str) -> bytes:
    """ Сваля файл от MinIO и връща неговите чисти байтове """
    try:
        response = s3_client.get_object(Bucket=BUCKET_NAME, Key=object_name)
        return response['Body'].read()
    except Exception as e:
        print(f"Error fetching from MinIO ({object_name}): {e}")
        raise e

def delete_file_from_cloud(object_name: str) -> bool:
    """ Изтрива файл от MinIO облака по неговото име или вътрешен път """
    if not object_name:
        return False
    try:
        prefix = f"/{BUCKET_NAME}/"
        if object_name.startswith(prefix):
            clean_name = object_name[len(prefix):]
        else:
            clean_name = object_name.lstrip("/")
        s3_client.delete_object(Bucket=BUCKET_NAME, Key=clean_name)
        return True
    except Exception as e:
        print(f"Error deleting from MinIO ({object_name}): {e}")
        return False

def delete_student_cloud_files(student_id_number: str, explicit_paths: list = None) -> int:
    """
    Изтрива всички файлове в MinIO, свързани със студента:
    1. Подадените изрични пътища (селфи, книжка).
    2. Всички обекти в кофата с префикс съответния факултетен номер (напр. селфита, книжки, протоколи).
    """
    deleted_count = 0
    cleaned_keys = set()

    if explicit_paths:
        prefix = f"/{BUCKET_NAME}/"
        for p in explicit_paths:
            if p:
                key = p[len(prefix):] if p.startswith(prefix) else p.lstrip("/")
                cleaned_keys.add(key)

    if student_id_number:
        try:
            prefixes_to_check = [f"{student_id_number}_", f"protocols/{student_id_number}_"]
            for pfx in prefixes_to_check:
                paginator = s3_client.get_paginator('list_objects_v2')
                for page in paginator.paginate(Bucket=BUCKET_NAME, Prefix=pfx):
                    for obj in page.get('Contents', []):
                        cleaned_keys.add(obj['Key'])
        except Exception as e:
            print(f"Error listing MinIO files for {student_id_number}: {e}")

    for key in cleaned_keys:
        try:
            s3_client.delete_object(Bucket=BUCKET_NAME, Key=key)
            deleted_count += 1
        except Exception as e:
            print(f"Error deleting object {key} from MinIO: {e}")

    return deleted_count
