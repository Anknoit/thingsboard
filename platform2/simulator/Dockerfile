FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy simulator source
COPY . .

# State file for injection persistence
ENV INJECTOR_STATE_FILE=/tmp/vantage_injections.json

# Default: run MQTT simulator + fault injector together via a wrapper
# Override CMD to run only one component if needed.
#
#   CMD ["python", "mqtt_sim.py"]          — simulator only
#   CMD ["python", "fault_injector.py"]    — injector only

CMD ["sh", "-c", "python fault_injector.py & python mqtt_sim.py"]

EXPOSE 8001
