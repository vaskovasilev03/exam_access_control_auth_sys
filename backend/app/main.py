from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def read_root():
    return {"status": "API is running", "database": "Connected (simulated)"}