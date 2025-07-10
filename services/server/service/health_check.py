import os
from threading import Thread
import requests
import time
from datetime import datetime, timezone


SLACK_CHANNEL = "C094Y8KQ4HL"
SLACK_DELAY = 1800
MESSAGE = "🚨 RMN service is not responding, but was alive on {}"


def start_health_check(interval: int = 900):
    slack = Slack()
    thread = Thread(target=slack.health_check, args=(interval,))
    print(f"✅ Health check thread started")
    thread.start()
    return thread


class Slack:
    def __init__(self):
        self.token = os.getenv("SLACK_TOKEN")
        self.header = {"Authorization": f"Bearer {self.token}"} if self.token is not None else None
        if self.token is None:
            self.header = {}
            print("WARNING: SLACK_TOKEN is not set in environment")
        else:
            self.header = {"Authorization": f"Bearer {self.token}"}

    def health_check(self, interval: int = 900):
        if self.token is None:
            print("SLACK_TOKEN is not set in environment, cannot run health check")
            return

        while True:
            print("Run health check on {}".format(datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")))
            try:
                ts = self.send_slack_message()
                self.cancel_old_slack_messages(ts)
            except Exception as e:
                print(e)
            time.sleep(interval)

    def send_slack_message(self):
        now = datetime.now()
        now_ts = int(now.timestamp())
        formatted = now.strftime("%A, %B %d, %Y at %I:%M %p")
        data = {
            "channel": SLACK_CHANNEL,
            "text": MESSAGE.format(formatted),
            "post_at": now_ts + SLACK_DELAY
        }

        try:
            response_message = self.post("https://slack.com/api/chat.scheduleMessage", data)
            json_message = response_message.json()
            if response_message.status_code != requests.codes.ok or not json_message["ok"]:
                print("❌ Slack message not sent:", response_message.status_code)
                print("Slack response for message:", json_message)
        except requests.exceptions.Timeout:
            print("❌ Timeout sending to Slack")
        return now_ts

    def cancel_old_slack_messages(self, ts):
        try:
            response_list = self.get_scheduled_messages()
            json_list = response_list.json()
            if response_list.status_code != requests.codes.ok or not json_list["ok"]:
                print("❌ Slack scheduled messages not received:", response_list.status_code)
                print("Slack response for list:", json_list)
                return False

            for message in json_list["scheduled_messages"]:
                if ts - message["date_created"] > 0:
                    response_delete = self.post(
                        "https://slack.com/api/chat.deleteScheduledMessage",
                        {
                            "channel": SLACK_CHANNEL,
                            "scheduled_message_id": message["id"]
                        }
                    )
                    json_delete = response_delete.json()
                    if response_delete.status_code != requests.codes.ok or not json_delete["ok"]:
                        print("Slack response for delete:", json_delete)
                        print("❌ Slack scheduled messages not deleted:", message["id"], response_delete.status_code)

        except requests.exceptions.Timeout:
            print("❌ Timeout sending to Slack")

    def get_scheduled_messages(self):
        return self.post("https://slack.com/api/chat.scheduledMessages.list", {"channel": SLACK_CHANNEL})

    def post(self, url, data):
        return requests.post(url, json=data, headers=self.header)

    def check_scheduled_messages(self):
        json_list = self.get_scheduled_messages().json()
        print(json_list)
        now_ts = int(datetime.now().timestamp())
        for message in json_list["scheduled_messages"]:
            print("Message to be posted in", message['post_at'] - now_ts, "seconds:", message)


if __name__ == "__main__":
    slack = Slack()
    slack.check_scheduled_messages()

    # t = start_health_check()
    # t.join()
