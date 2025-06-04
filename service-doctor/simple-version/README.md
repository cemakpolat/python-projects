## 🩺 A Lightweight Service Doctor for Linux Environments

This tool monitors critical Linux services and notifies you in case of failures. Follow these steps to set it up in your environment:

### 🔧 Setup Instructions

1. **Make Shell Scripts Executable**
   Grant execution permissions to the setup and runner scripts:

   ```bash
   chmod +x prepare_env.sh run_service_monitor.sh
   ```

2. **Install Dependencies**
   Run the setup script to install Python, Docker, and Docker Compose:

   ```bash
   ./prepare_env.sh
   ```

3. **Configure Your Environment**

   * Edit the `.env` file to provide necessary credentials (e.g., email, database passwords, webhook URLs).
   * Update `config.json` to reflect the services you want to monitor and which integrations to enable.

4. **Start the Service Doctor**
   Launch the monitoring application with:

   ```bash
   ./run_service_monitor.sh
   ```

