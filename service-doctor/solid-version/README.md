## 🩺 A Lightweight Service Doctor for Linux Environments (Powered by SOLID Principles)

To get started, follow the steps below to set up and run the Service Doctor application in your Linux environment.

### 🔧 Setup Instructions

1. **Make Shell Scripts Executable**
   Grant execute permission to the setup and management scripts:

   ```bash
   chmod +x prepare_env.sh run_service_doctor.sh
   ```

2. **Install Dependencies**
   Run the environment setup script to install Python, Docker, and Docker Compose:

   ```bash
   ./prepare_env.sh
   ```

3. **Configure Environment Variables**
   The `.env` file holds all sensitive credentials (e.g., email, Redis, MongoDB, Slack/Teams webhooks).
   Copy the example file and update it with your configuration:

   ```bash
   cp env .env
   ```

4. **Update Service Configuration (Optional)**
   You can customize which services are monitored or disabled by editing the `config.json` file.

---

### 🚀 Running the Service Doctor

Use the `run_service_doctor.sh` script to control the application:

* **Start the Application**
  Launch all required services and the monitoring app:

  ```bash
  ./run_service_doctor.sh start
  ```

* **Watch Logs**
  Stream application logs in real-time:

  ```bash
  ./run_service_doctor.sh watch
  ```

* **Stop the Application**
  Gracefully shut down all services:

  ```bash
  ./run_service_doctor.sh stop
  ```

* **Restart the Application**
  Stop and immediately restart the app and related services:

  ```bash
  ./run_service_doctor.sh restart
  ```

* **Clean Up**
  Remove Docker containers, volumes, networks, and the Python virtual environment:

  ```bash
  ./run_service_doctor.sh clean
  ```
