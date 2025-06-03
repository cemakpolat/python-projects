#!/usr/bin/env python3

import subprocess
import schedule
import time
import smtplib
import logging
import json
import os
from datetime import datetime, timedelta
from collections import defaultdict
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests  # For Slack notifications
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("service_doctor.log"),
        logging.StreamHandler()
    ]
)

CONFIG = {}

# Load configuration from file if exists, and override with environment variables
def load_config():
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                user_config = json.load(f)
                CONFIG.update(user_config)  # Replace or merge entire config
            logging.info(f"Loaded configuration from {config_path}")
        except Exception as e:
            logging.error(f"Failed to load configuration from {config_path}: {e}")
    
    influx_config = CONFIG["influxdb"]
    
    
    # Enable InfluxDB logging if token, org, and bucket are provided
    if influx_config["enabled"] == True:
        
        influx_config["url"] = os.getenv("INFLUXDB_URL", influx_config["url"])
        influx_config["token"] = os.getenv("INFLUXDB_TOKEN", influx_config["token"])
        influx_config["org"] = os.getenv("INFLUXDB_ORG", influx_config["org"])
        influx_config["bucket"] = os.getenv("INFLUXDB_BUCKET", influx_config["bucket"])
        
        if influx_config["token"] and influx_config["org"] and influx_config["bucket"]:
            logging.info("InfluxDB logging enabled based on environment variables.")
        else:
            influx_config["enabled"] = False
            logging.warning("InfluxDB logging disabled. Missing INFLUXDB_TOKEN, INFLUXDB_ORG, or INFLUXDB_BUCKET environment variables.")

    # Email password
    if CONFIG["notification"]["email"]["enabled"]:
        email_config = CONFIG["notification"]["email"]
        email_config["password"] = os.getenv("EMAIL_PASSWORD", email_config["password"])
        if not email_config["password"]:
             logging.warning("Email notifications enabled but EMAIL_PASSWORD environment variable is not set.")

    # Slack Webhook URL
    if CONFIG["notification"]["slack"]["enabled"]:
        slack_config = CONFIG["notification"]["slack"]
        slack_config["webhook_url"] = os.getenv("SLACK_WEBHOOK_URL", slack_config["webhook_url"])
        if not slack_config["webhook_url"]:
            logging.warning("Slack notifications enabled but SLACK_WEBHOOK_URL environment variable is not set.")

    # Teams Webhook URL (assuming similar env var naming)
    if CONFIG["notification"]["teams"]["enabled"]:
        teams_config = CONFIG["notification"]["teams"]
        teams_config["webhook_url"] = os.getenv("TEAMS_WEBHOOK_URL", teams_config["webhook_url"])
        if not teams_config["webhook_url"]:
            logging.warning("Teams notifications enabled but TEAMS_WEBHOOK_URL environment variable is not set.")


    logging.debug(f"Final Configuration (after env override): {CONFIG}")


# Service failure tracking
service_failures = defaultdict(list)

def check_service(service_name):
    """Check if a service is running using systemctl."""

    try:
        result = subprocess.run(
            ["systemctl", "is-active", service_name],
            capture_output=True,
            text=True,
            check=False
        )
        return result.stdout.strip() == "active"
    except FileNotFoundError:
        logging.error("systemctl command not found. Are you running in a systemd-enabled environment?")
        return False
    except Exception as e:
        logging.error(f"Error checking service {service_name}: {e}")
        return False

def restart_service(service_name):
    """Attempt to restart a service."""
    try:
        # Removing sudo as it's unlikely to work in a standard container
        result = subprocess.run(
            ["systemctl", "restart", service_name],
            capture_output=True,
            text=True,
            check=False
        )
        success = result.returncode == 0
        if success:
            logging.info(f"Successfully restarted service {service_name}")
        else:
            logging.error(f"Failed to restart service {service_name}: {result.stderr}")
        return success
    except FileNotFoundError:
         logging.error("systemctl command not found. Cannot restart service.")
         return False
    except Exception as e:
        logging.error(f"Error restarting service {service_name}: {e}")
        return False

def record_failure(service_name):
    """Record a service failure with timestamp."""
    now = datetime.now()
    service_failures[service_name].append(now)

    # Clean up old failure records
    cutoff_time = now - timedelta(hours=CONFIG["alert_window_hours"])
    service_failures[service_name] = [t for t in service_failures[service_name] if t >= cutoff_time]

    # Check if we need to send an alert
    if len(service_failures[service_name]) >= CONFIG["alert_threshold"]:
        send_alert(service_name)

    # Save failure event to InfluxDB
    if CONFIG["influxdb"]["enabled"]:
        save_to_influxdb(service_name, "failure", success=False)


def send_email_alert(service_name):
    """Send an email alert about repeated service failures."""
    email_config = CONFIG["notification"]["email"]
    if not email_config["enabled"] or not email_config["password"]:
        logging.debug("Email notifications not enabled or password missing.")
        return

    try:
        msg = MIMEMultipart()
        msg["From"] = email_config["sender_email"]
        msg["To"] = email_config["receiver_email"]
        msg["Subject"] = f"ALERT: Service {service_name} has failed multiple times"

        # Email body
        failures = service_failures[service_name]
        body = f"""
        The service {service_name} has failed {len(failures)} times in the past {CONFIG['alert_window_hours']} hour(s).

        Failure timestamps:
        {chr(10).join([t.strftime('%Y-%m-%d %H:%M:%S') for t in failures])}

        Automated attempts to restart the service have been unsuccessful (or attempted).
        Please check the system manually.

        --
        Linux Service Doctor
        """

        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(email_config["smtp_server"], email_config["smtp_port"]) as server:
            server.starttls()
            server.login(email_config["sender_email"], email_config["password"])
            server.send_message(msg)

        logging.info(f"Email alert sent for service {service_name}")
    except Exception as e:
        logging.error(f"Failed to send email alert for service {service_name}: {e}")

def send_slack_alert(service_name):
    """Send a Slack alert about repeated service failures."""
    slack_config = CONFIG["notification"]["slack"]
    if not slack_config["enabled"] or not slack_config["webhook_url"]:
        logging.debug("Slack notifications not enabled or webhook URL missing.")
        return

    try:
        webhook_url = slack_config["webhook_url"]
        failures = service_failures[service_name]

        message = {
            "text": f"🚨 *ALERT*: Service `{service_name}` has failed multiple times",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"🚨 *ALERT*: Service `{service_name}` has failed {len(failures)} times in the past {CONFIG['alert_window_hours']} hour(s)."
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Failure timestamps:*\n" + "\n".join([t.strftime('• %Y-%m-%d %H:%M:%S') for t in failures])
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "Automated attempts to restart the service have been unsuccessful (or attempted). Please check the system manually."
                    }
                }
            ]
        }

        response = requests.post(webhook_url, json=message)
        if response.status_code == 200:
            logging.info(f"Slack alert sent for service {service_name}")
        else:
            logging.error(f"Failed to send Slack alert: {response.status_code} - {response.text}")
    except Exception as e:
        logging.error(f"Failed to send Slack alert for service {service_name}: {e}")

# Assuming Teams works similarly to Slack webhooks
def send_teams_alert(service_name):
    """Send a Microsoft Teams alert about repeated service failures."""
    teams_config = CONFIG["notification"]["teams"]
    if not teams_config["enabled"] or not teams_config["webhook_url"]:
        logging.debug("Teams notifications not enabled or webhook URL missing.")
        return

    try:
        webhook_url = teams_config["webhook_url"]
        failures = service_failures[service_name]

        # Teams webhook payload structure can vary, this is a basic card
        message = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "summary": f"ALERT: Service {service_name} has failed multiple times",
            "sections": [{
                "activityTitle": f"Service Failure Alert: {service_name}",
                "activitySubtitle": f"Failed {len(failures)} times in the past {CONFIG['alert_window_hours']} hour(s)",
                "facts": [{
                    "name": "Failure Timestamps",
                    "value": "\n".join([t.strftime('%Y-%m-%d %H:%M:%S') for t in failures])
                }],
                "text": "Automated attempts to restart the service have been unsuccessful (or attempted). Please check the system manually."
            }],
            "themeColor": "FF0000" # Red color for alert
        }

        response = requests.post(webhook_url, json=message)
        # Teams webhooks return 200 OK on success
        if response.status_code == 200:
            logging.info(f"Teams alert sent for service {service_name}")
        else:
            # Teams webhooks might return 400 if payload is malformed
            logging.error(f"Failed to send Teams alert: {response.status_code} - {response.text}")
    except Exception as e:
        logging.error(f"Failed to send Teams alert for service {service_name}: {e}")


def send_alert(service_name):
    """Send alerts through configured channels."""
    logging.warning(f"Alert triggered for service {service_name} - {len(service_failures[service_name])} failures")

    if CONFIG["notification"]["email"]["enabled"]:
        send_email_alert(service_name)

    if CONFIG["notification"]["slack"]["enabled"]:
        send_slack_alert(service_name)
    if CONFIG["notification"]["teams"]["enabled"]:
        send_teams_alert(service_name)

# --- End Alert Sending Functions ---


# --- InfluxDB 2.x Data Writing ---
def save_to_influxdb(service_name, event_type, success=False):
    """Save event data to InfluxDB 2.x."""
    influx_config = CONFIG["influxdb"]
    if not influx_config["enabled"]:
        return

    # Check if essential InfluxDB 2.x parameters are available
    if not influx_config.get("url") or not influx_config.get("token") or \
       not influx_config.get("org") or not influx_config.get("bucket"):
        logging.error("InfluxDB 2.x logging is enabled but connection parameters (URL, Token, Org, Bucket) are missing.")
        return

    try:
        
        with InfluxDBClient(url=influx_config["url"], token=influx_config["token"], org=influx_config["org"]) as client:
            # Use the write_api with SYNCHRONOUS mode for immediate write (simple, but less performant for bulk)
            # For better performance, use ASYNCHRONOUS or BATCHING
            write_api = client.write_api(write_options=SYNCHRONOUS)

            # Create a data point
            point = Point("service_events") \
                .tag("service", service_name) \
                .tag("event_type", event_type) \
                .field("success", success) \
                .field("value", 1 if event_type != "check" else (1 if success else 0)) \
                .time(datetime.utcnow(), WritePrecision.NS) # Use UTC and nanosecond precision

            # Write the point to the specified bucket
            write_api.write(bucket=influx_config["bucket"], record=point)

        logging.debug(f"Saved {event_type} event for {service_name} to InfluxDB 2.x bucket {influx_config['bucket']}")
    except Exception as e:
        logging.error(f"Failed to save data to InfluxDB 2.x: {e}")

def scan_services():
    """Scan all configured services and handle any that are down."""
    logging.info("Starting service scan...")

    for service in CONFIG["services"]:
        logging.debug(f"Checking service: {service}")

        if check_service(service):
            logging.debug(f"Service {service} is running")
            # Optionally log successful check
            if CONFIG["influxdb"]["enabled"]:
                 save_to_influxdb(service, "check", True)
        else:
            logging.warning(f"Service {service} is down, attempting to restart")

            restart_success = restart_service(service)

            if restart_success:
                logging.info(f"Service {service} restarted successfully")
                if CONFIG["influxdb"]["enabled"]:
                    save_to_influxdb(service, "restart", True)
            else:
                logging.error(f"Failed to restart service {service}")
                record_failure(service) # This will also trigger alert logic and save to InfluxDB

    logging.info("Service scan completed")

def main():
    """Main function to schedule and run the service doctor."""
    load_config()

    logging.info("Linux Service Doctor starting...")
    if not CONFIG["services"]:
         logging.warning("No services configured for monitoring in CONFIG['services']. The script will run but do nothing.")
    else:
        logging.info(f"Monitoring services: {', '.join(CONFIG['services'])}")
    logging.info(f"Scan interval: {CONFIG['scan_interval_minutes']} minutes")
    if CONFIG["influxdb"]["enabled"]:
        logging.info(f"InfluxDB logging enabled. URL: {CONFIG['influxdb']['url']}, Org: {CONFIG['influxdb']['org']}, Bucket: {CONFIG['influxdb']['bucket']}")
    else:
        logging.warning("InfluxDB logging is disabled.")


    # Run once immediately (only if services are configured)
    if CONFIG["services"]:
        scan_services()
    else:
        logging.info("Skipping initial scan as no services are configured.")


    # Schedule regular scans (only if services are configured)
    if CONFIG["services"]:
        schedule.every(CONFIG["scan_interval_minutes"]).minutes.do(scan_services)
        logging.info(f"Scheduling scans every {CONFIG['scan_interval_minutes']} minutes.")
    else:
        logging.info("No services configured, scheduling skipped.")


    # Keep the script running
    logging.info("Service monitoring is active")
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Service monitoring stopped by user")
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        return 1

    return 0

if __name__ == "__main__":
    exit(main())