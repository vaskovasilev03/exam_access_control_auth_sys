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
