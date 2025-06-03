
# A Lightweight Service Doctor/Monitor for Linux Environments using SOLID principles

Add executable permission for the files  `prepare_env.sh` and `run_service_monitor.sh` via `chmod +x`

Run `prepare_env.sh` to install python, docker and docker compose

env file includes all credentials, therefore you need to configure it and copy to .env file as given below:

`copy env .env`

If you need to adapt the services to be checked, you can confifure `config.sjon` such as enabling a service or disabling it.


Once we are done with the required libraries and configuration, we can utilize `run_service_doctor.sh` command to perform a number of operaitons, e.g.

Start:

 `run_service_doctor.sh start` 

Watch Logs:

`run_service_doctor.sh watch` 

Stop apps:

`run_service_doctor.sh stop` 

Restart apps:

`run_service_doctor.sh restart` 

Clean all containers and related networks and volumes, as well as virtual environment for python is removed as well.

`run_service_doctor.sh clean` 


