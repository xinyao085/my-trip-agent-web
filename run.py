import uvicorn

if __name__ == "__main__":
    # 开发时开启 reload=True；生产环境去掉 reload，改用 gunicorn + uvicorn worker
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8080, reload=True)
