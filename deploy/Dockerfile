FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
COPY . /app
RUN python -m compileall -q shared vm.py
CMD ["python", "vm.py", "supervise-loop", "--apply", "--interval", "60"]
