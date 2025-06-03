#!/usr/bin/env python3

import subprocess
import schedule
import time
import smtplib
import logging
import json
import os
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from collections import defaultdict
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum

import requests
import redis
import pymongo
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

# Enums and Data Classes
class EventType(Enum):
    CHECK = "check"
    RESTART = "restart"
    FAILURE = "failure"

class NotificationType(Enum):
    EMAIL = "email"
    SLACK = "slack"
    TEAMS = "teams"

@dataclass
class ServiceEvent:
    service_name: str
    event_type: EventType
    success: bool
    timestamp: datetime
    message: Optional[str] = None

@dataclass
class NotificationConfig:
    notification_type: NotificationType
    enabled: bool
    config: Dict[str, Any]

@dataclass
class DatabaseConfig:
    db_type: str
    enabled: bool
    config: Dict[str, Any]

# Interfaces (Abstract Base Classes)
class ServiceChecker(ABC):
    """Interface for checking service status"""
    
    @abstractmethod
    def is_service_running(self, service_name: str) -> bool:
        pass

class ServiceManager(ABC):
    """Interface for managing services"""
    
    @abstractmethod
    def restart_service(self, service_name: str) -> bool:
        pass

class NotificationSender(ABC):
    """Interface for sending notifications"""
    
    @abstractmethod
    def send_notification(self, service_name: str, failures: List[datetime], config: Dict[str, Any]) -> bool:
        pass

class DatabaseRepository(ABC):
    """Interface for database operations"""
    
    @abstractmethod
    def save_event(self, event: ServiceEvent) -> bool:
        pass
    
    @abstractmethod
    def get_failures(self, service_name: str, since: datetime) -> List[datetime]:
        pass
    
    @abstractmethod
    def cleanup_old_records(self, cutoff_time: datetime) -> None:
        pass

# Concrete Implementations

# Service Checker Implementation
class SystemdServiceChecker(ServiceChecker):
    """Concrete implementation for checking systemd services"""
    
    def is_service_running(self, service_name: str) -> bool:
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

# Service Manager Implementation
class SystemdServiceManager(ServiceManager):
    """Concrete implementation for managing systemd services"""
    
    def restart_service(self, service_name: str) -> bool:
        try:
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

# Notification Senders
class EmailNotificationSender(NotificationSender):
    """Email notification sender"""
    
    def send_notification(self, service_name: str, failures: List[datetime], config: Dict[str, Any]) -> bool:
        if not config.get("password"):
            logging.debug("Email password missing.")
            return False
        
        try:
            msg = MIMEMultipart()
            msg["From"] = config["sender_email"]
            msg["To"] = config["receiver_email"]
            msg["Subject"] = f"ALERT: Service {service_name} has failed multiple times"
            
            body = f"""
            The service {service_name} has failed {len(failures)} times recently.
            
            Failure timestamps:
            {chr(10).join([t.strftime('%Y-%m-%d %H:%M:%S') for t in failures])}
            
            Please check the system manually.
            
            --
            Linux Service Doctor
            """
            
            msg.attach(MIMEText(body, "plain"))
            
            with smtplib.SMTP(config["smtp_server"], config["smtp_port"]) as server:
                server.starttls()
                server.login(config["sender_email"], config["password"])
                server.send_message(msg)
            
            logging.info(f"Email alert sent for service {service_name}")
            return True
        except Exception as e:
            logging.error(f"Failed to send email alert for service {service_name}: {e}")
            return False

class SlackNotificationSender(NotificationSender):
    """Slack notification sender"""
    
    def send_notification(self, service_name: str, failures: List[datetime], config: Dict[str, Any]) -> bool:
        if not config.get("webhook_url"):
            logging.debug("Slack webhook URL missing.")
            return False
        
        try:
            message = {
                "text": f"🚨 *ALERT*: Service `{service_name}` has failed multiple times",
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"🚨 *ALERT*: Service `{service_name}` has failed {len(failures)} times recently."
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Failure timestamps:*\n" + "\n".join([t.strftime('• %Y-%m-%d %H:%M:%S') for t in failures])
                        }
                    }
                ]
            }
            
            response = requests.post(config["webhook_url"], json=message)
            if response.status_code == 200:
                logging.info(f"Slack alert sent for service {service_name}")
                return True
            else:
                logging.error(f"Failed to send Slack alert: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            logging.error(f"Failed to send Slack alert for service {service_name}: {e}")
            return False

class TeamsNotificationSender(NotificationSender):
    """Microsoft Teams notification sender"""
    
    def send_notification(self, service_name: str, failures: List[datetime], config: Dict[str, Any]) -> bool:
        if not config.get("webhook_url"):
            logging.debug("Teams webhook URL missing.")
            return False
        
        try:
            message = {
                "@type": "MessageCard",
                "@context": "http://schema.org/extensions",
                "summary": f"ALERT: Service {service_name} has failed multiple times",
                "sections": [{
                    "activityTitle": f"Service Failure Alert: {service_name}",
                    "activitySubtitle": f"Failed {len(failures)} times recently",
                    "facts": [{
                        "name": "Failure Timestamps",
                        "value": "\n".join([t.strftime('%Y-%m-%d %H:%M:%S') for t in failures])
                    }],
                    "text": "Please check the system manually."
                }],
                "themeColor": "FF0000"
            }
            
            response = requests.post(config["webhook_url"], json=message)
            if response.status_code == 200:
                logging.info(f"Teams alert sent for service {service_name}")
                return True
            else:
                logging.error(f"Failed to send Teams alert: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            logging.error(f"Failed to send Teams alert for service {service_name}: {e}")
            return False

# Database Repositories
class InfluxDBRepository(DatabaseRepository):
    """InfluxDB repository implementation"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._client = None
    
    @property
    def client(self):
        if self._client is None:
            self._client = InfluxDBClient(
                url=self.config["url"],
                token=self.config["token"],
                org=self.config["org"]
            )
        return self._client
    
    def save_event(self, event: ServiceEvent) -> bool:
        try:
            write_api = self.client.write_api(write_options=SYNCHRONOUS)
            
            point = Point("service_events") \
                .tag("service", event.service_name) \
                .tag("event_type", event.event_type.value) \
                .field("success", event.success) \
                .field("value", 1 if event.event_type != EventType.CHECK else (1 if event.success else 0)) \
                .time(event.timestamp, WritePrecision.NS)
            
            write_api.write(bucket=self.config["bucket"], record=point)
            logging.debug(f"Saved {event.event_type.value} event for {event.service_name} to InfluxDB")
            return True
        except Exception as e:
            logging.error(f"Failed to save event to InfluxDB: {e}")
            return False
    
    def get_failures(self, service_name: str, since: datetime) -> List[datetime]:
        # InfluxDB query implementation would go here
        # For now, returning empty list as this requires complex query logic
        return []
    
    def cleanup_old_records(self, cutoff_time: datetime) -> None:
        # InfluxDB cleanup logic would go here
        pass

class RedisRepository(DatabaseRepository):
    """Redis repository implementation"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._client = None
    
    @property
    def client(self):
        if self._client is None:
            self._client = redis.Redis(
                host=self.config.get("host", "localhost"),
                port=self.config.get("port", 6379),
                password=self.config.get("password"),
                decode_responses=True
            )
        return self._client
    
    def save_event(self, event: ServiceEvent) -> bool:
        try:
            event_data = {
                "service_name": event.service_name,
                "event_type": event.event_type.value,
                "success": event.success,
                "timestamp": event.timestamp.isoformat(),
                "message": event.message or ""
            }
            
            # Store in a sorted set for easy time-based queries
            key = f"service_events:{event.service_name}"
            score = event.timestamp.timestamp()
            
            self.client.zadd(key, {json.dumps(event_data): score})
            
            # Also store failures in a separate key for quick access
            if event.event_type == EventType.FAILURE:
                failure_key = f"service_failures:{event.service_name}"
                self.client.zadd(failure_key, {event.timestamp.isoformat(): score})
            
            logging.debug(f"Saved {event.event_type.value} event for {event.service_name} to Redis")
            return True
        except Exception as e:
            logging.error(f"Failed to save event to Redis: {e}")
            return False
    
    def get_failures(self, service_name: str, since: datetime) -> List[datetime]:
        try:
            key = f"service_failures:{service_name}"
            since_timestamp = since.timestamp()
            
            # Get failures since the specified time
            failure_timestamps = self.client.zrangebyscore(key, since_timestamp, "+inf")
            return [datetime.fromisoformat(ts) for ts in failure_timestamps]
        except Exception as e:
            logging.error(f"Failed to get failures from Redis: {e}")
            return []
    
    def cleanup_old_records(self, cutoff_time: datetime) -> None:
        try:
            cutoff_timestamp = cutoff_time.timestamp()
            
            # Get all service failure keys
            failure_keys = self.client.keys("service_failures:*")
            event_keys = self.client.keys("service_events:*")
            
            for key in failure_keys + event_keys:
                self.client.zremrangebyscore(key, "-inf", cutoff_timestamp)
            
            logging.debug(f"Cleaned up old records before {cutoff_time}")
        except Exception as e:
            logging.error(f"Failed to cleanup old records in Redis: {e}")

class MongoDBRepository(DatabaseRepository):
    """MongoDB repository implementation"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._client = None
        self._db = None
    
    @property
    def client(self):
        if self._client is None:
            connection_string = self.config.get("connection_string", "mongodb://localhost:27017")
            self._client = pymongo.MongoClient(connection_string)
        return self._client
    
    @property
    def db(self):
        if self._db is None:
            db_name = self.config.get("database", "service_doctor")
            self._db = self.client[db_name]
        return self._db
    
    def save_event(self, event: ServiceEvent) -> bool:
        try:
            collection = self.db.service_events
            
            event_doc = {
                "service_name": event.service_name,
                "event_type": event.event_type.value,
                "success": event.success,
                "timestamp": event.timestamp,
                "message": event.message or ""
            }
            
            collection.insert_one(event_doc)
            logging.debug(f"Saved {event.event_type.value} event for {event.service_name} to MongoDB")
            return True
        except Exception as e:
            logging.error(f"Failed to save event to MongoDB: {e}")
            return False
    
    def get_failures(self, service_name: str, since: datetime) -> List[datetime]:
        try:
            collection = self.db.service_events
            
            query = {
                "service_name": service_name,
                "event_type": EventType.FAILURE.value,
                "timestamp": {"$gte": since}
            }
            
            failures = collection.find(query, {"timestamp": 1})
            return [doc["timestamp"] for doc in failures]
        except Exception as e:
            logging.error(f"Failed to get failures from MongoDB: {e}")
            return []
    
    def cleanup_old_records(self, cutoff_time: datetime) -> None:
        try:
            collection = self.db.service_events
            result = collection.delete_many({"timestamp": {"$lt": cutoff_time}})
            logging.debug(f"Cleaned up {result.deleted_count} old records before {cutoff_time}")
        except Exception as e:
            logging.error(f"Failed to cleanup old records in MongoDB: {e}")

# Factory Classes
class NotificationSenderFactory:
    """Factory for creating notification senders"""
    
    _senders = {
        NotificationType.EMAIL: EmailNotificationSender,
        NotificationType.SLACK: SlackNotificationSender,
        NotificationType.TEAMS: TeamsNotificationSender,
    }
    
    @classmethod
    def create_sender(cls, notification_type: NotificationType) -> NotificationSender:
        sender_class = cls._senders.get(notification_type)
        if not sender_class:
            raise ValueError(f"Unknown notification type: {notification_type}")
        return sender_class()

class DatabaseRepositoryFactory:
    """Factory for creating database repositories"""
    
    @classmethod
    def create_repository(cls, db_config: DatabaseConfig) -> DatabaseRepository:
        if db_config.db_type.lower() == "influxdb":
            return InfluxDBRepository(db_config.config)
        elif db_config.db_type.lower() == "redis":
            return RedisRepository(db_config.config)
        elif db_config.db_type.lower() == "mongodb":
            return MongoDBRepository(db_config.config)
        else:
            raise ValueError(f"Unknown database type: {db_config.db_type}")

# Configuration Manager
class ConfigurationManager:
    """Handles loading and managing configuration"""
    
    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self.config = {}
    
    def load_config(self) -> Dict[str, Any]:
        """Load configuration from file and environment variables"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    self.config = json.load(f)
                logging.info(f"Loaded configuration from {self.config_path}")
            except Exception as e:
                logging.error(f"Failed to load configuration from {self.config_path}: {e}")
        
        self._override_with_env_vars()
        return self.config
    
    def _override_with_env_vars(self):
        """Override configuration with environment variables"""
        # Database configurations
        for db_config in self.config.get("databases", []):
            if db_config["type"] == "influxdb":
                db_config["config"]["url"] = os.getenv("INFLUXDB_URL", db_config["config"].get("url"))
                db_config["config"]["token"] = os.getenv("INFLUXDB_TOKEN", db_config["config"].get("token"))
                db_config["config"]["org"] = os.getenv("INFLUXDB_ORG", db_config["config"].get("org"))
                db_config["config"]["bucket"] = os.getenv("INFLUXDB_BUCKET", db_config["config"].get("bucket"))
            elif db_config["type"] == "redis":
                db_config["config"]["host"] = os.getenv("REDIS_HOST", db_config["config"].get("host"))
                db_config["config"]["port"] = int(os.getenv("REDIS_PORT", db_config["config"].get("port", 6379)))
                db_config["config"]["password"] = os.getenv("REDIS_PASSWORD", db_config["config"].get("password"))
            elif db_config["type"] == "mongodb":
                db_config["config"]["connection_string"] = os.getenv("MONGODB_CONNECTION_STRING", 
                                                                   db_config["config"].get("connection_string"))
        
        # Notification configurations
        for notif_config in self.config.get("notifications", []):
            if notif_config["type"] == "email":
                notif_config["config"]["password"] = os.getenv("EMAIL_PASSWORD", notif_config["config"].get("password"))
            elif notif_config["type"] == "slack":
                notif_config["config"]["webhook_url"] = os.getenv("SLACK_WEBHOOK_URL", notif_config["config"].get("webhook_url"))
            elif notif_config["type"] == "teams":
                notif_config["config"]["webhook_url"] = os.getenv("TEAMS_WEBHOOK_URL", notif_config["config"].get("webhook_url"))

# Main Service Doctor Class
class ServiceDoctor:
    """Main service monitoring class that orchestrates all components"""
    
    def __init__(self, config_manager: ConfigurationManager):
        self.config_manager = config_manager
        self.config = config_manager.load_config()
        
        # Initialize components
        self.service_checker = SystemdServiceChecker()
        self.service_manager = SystemdServiceManager()
        
        # Initialize databases
        self.databases = []
        for db_config_dict in self.config.get("databases", []):
            if db_config_dict.get("enabled", False):
                db_config = DatabaseConfig(
                    db_type=db_config_dict["type"],
                    enabled=db_config_dict["enabled"],
                    config=db_config_dict["config"]
                )
                try:
                    repository = DatabaseRepositoryFactory.create_repository(db_config)
                    self.databases.append(repository)
                    logging.info(f"Initialized {db_config.db_type} database")
                except Exception as e:
                    logging.error(f"Failed to initialize {db_config.db_type} database: {e}")
        
        # Initialize notification senders
        self.notification_configs = []
        for notif_config_dict in self.config.get("notifications", []):
            if notif_config_dict.get("enabled", False):
                notif_config = NotificationConfig(
                    notification_type=NotificationType(notif_config_dict["type"]),
                    enabled=notif_config_dict["enabled"],
                    config=notif_config_dict["config"]
                )
                self.notification_configs.append(notif_config)
        
        # In-memory failure tracking (fallback)
        self.service_failures = defaultdict(list)
    
    def save_event(self, event: ServiceEvent):
        """Save event to all configured databases"""
        for db in self.databases:
            try:
                db.save_event(event)
            except Exception as e:
                logging.error(f"Failed to save event to database: {e}")
    
    def get_recent_failures(self, service_name: str) -> List[datetime]:
        """Get recent failures for a service"""
        cutoff_time = datetime.now() - timedelta(hours=self.config.get("alert_window_hours", 1))
        
        # Try to get from database first
        for db in self.databases:
            try:
                failures = db.get_failures(service_name, cutoff_time)
                if failures:
                    return failures
            except Exception as e:
                logging.error(f"Failed to get failures from database: {e}")
        
        # Fallback to in-memory tracking
        self.service_failures[service_name] = [
            t for t in self.service_failures[service_name] if t >= cutoff_time
        ]
        return self.service_failures[service_name]
    
    def record_failure(self, service_name: str):
        """Record a service failure"""
        now = datetime.now()
        
        # Save to databases
        event = ServiceEvent(
            service_name=service_name,
            event_type=EventType.FAILURE,
            success=False,
            timestamp=now
        )
        self.save_event(event)
        
        # Also track in memory for fallback
        self.service_failures[service_name].append(now)
        
        # Check if alert should be sent
        recent_failures = self.get_recent_failures(service_name)
        alert_threshold = self.config.get("alert_threshold", 3)
        
        if len(recent_failures) >= alert_threshold:
            self.send_alerts(service_name, recent_failures)
    
    def send_alerts(self, service_name: str, failures: List[datetime]):
        """Send alerts through all configured channels"""
        logging.warning(f"Alert triggered for service {service_name} - {len(failures)} failures")
        
        for notif_config in self.notification_configs:
            try:
                sender = NotificationSenderFactory.create_sender(notif_config.notification_type)
                sender.send_notification(service_name, failures, notif_config.config)
            except Exception as e:
                logging.error(f"Failed to send {notif_config.notification_type.value} notification: {e}")
    
    def scan_services(self):
        """Scan all configured services"""
        logging.info("Starting service scan...")
        
        for service in self.config.get("services", []):
            logging.debug(f"Checking service: {service}")
            
            if self.service_checker.is_service_running(service):
                logging.debug(f"Service {service} is running")
                # Save successful check event
                event = ServiceEvent(
                    service_name=service,
                    event_type=EventType.CHECK,
                    success=True,
                    timestamp=datetime.now()
                )
                self.save_event(event)
            else:
                logging.warning(f"Service {service} is down, attempting to restart")
                
                restart_success = self.service_manager.restart_service(service)
                
                # Save restart event
                restart_event = ServiceEvent(
                    service_name=service,
                    event_type=EventType.RESTART,
                    success=restart_success,
                    timestamp=datetime.now()
                )
                self.save_event(restart_event)
                
                if restart_success:
                    logging.info(f"Service {service} restarted successfully")
                else:
                    logging.error(f"Failed to restart service {service}")
                    self.record_failure(service)
        
        logging.info("Service scan completed")
    
    def cleanup_old_data(self):
        """Clean up old data from databases"""
        cutoff_time = datetime.now() - timedelta(hours=self.config.get("retention_hours", 24))
        
        for db in self.databases:
            try:
                db.cleanup_old_records(cutoff_time)
            except Exception as e:
                logging.error(f"Failed to cleanup old data: {e}")
    
    def run(self):
        """Main run loop"""
        logging.info("Linux Service Doctor starting...")
        
        services = self.config.get("services", [])
        if not services:
            logging.warning("No services configured for monitoring.")
            return
        
        logging.info(f"Monitoring services: {', '.join(services)}")
        logging.info(f"Scan interval: {self.config.get('scan_interval_minutes', 5)} minutes")
        
        # Run initial scan
        self.scan_services()
        
        # Schedule regular scans
        scan_interval = self.config.get("scan_interval_minutes", 5)
        schedule.every(scan_interval).minutes.do(self.scan_services)
        
        # Schedule cleanup
        schedule.every(1).hours.do(self.cleanup_old_data)
        
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

def main():
    """Main function"""
    config_manager = ConfigurationManager()
    service_doctor = ServiceDoctor(config_manager)
    return service_doctor.run()

if __name__ == "__main__":
    exit(main())