import os
import requests
import random
import time

ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
IG_USER_ID = os.getenv("IG_USER_ID")

FRIENDLY_REPLIES = {
    "hello": ["Hey 👋 How’s it going?", "Hello there! 😃 Hope your day’s going well."],
    "thanks": ["You’re most welcome 🤝", "Anytime! 🙌"],
    "useful": ["So happy it helped you 💡✨", "That’s great to hear! 🙏"]
}

def get_recent_media():
    url = f"https://graph.facebook.com/v17.0/{IG_USER_ID}/media"
    params = {"fields": "id,caption", "access_token": ACCESS_TOKEN}
    res = requests.get(url, params=params).json()
    return res.get("data", [])

def get_comments(media_id):
    url = f"https://graph.facebook.com/v17.0/{media_id}/comments"
    params = {"fields": "id,text,username", "access_token": ACCESS_TOKEN}
    res = requests.get(url, params=params).json()
    return res.get("data", [])

def has_replies(comment_id):
    url = f"https://graph.facebook.com/v17.0/{comment_id}/replies"
    params = {"fields": "id", "access_token": ACCESS_TOKEN}
    res = requests.get(url, params=params).json()
    return bool(res.get("data", []))

def reply_to_comment(comment_id, message):
    url = f"https://graph.facebook.com/v17.0/{comment_id}/replies"
    params = {"message": message, "access_token": ACCESS_TOKEN}
    return requests.post(url, data=params).json()

def auto_reply():
    media = get_recent_media()
    for post in media:
        comments = get_comments(post["id"])
        for comment in comments:
            if not has_replies(comment["id"]):  # only reply if no reply exists
                text = comment["text"].lower()
                reply = None
                for key, responses in FRIENDLY_REPLIES.items():
                    if key in text:
                        reply = random.choice(responses)
                        break
                if reply:
                    result = reply_to_comment(comment["id"], reply)
                    print(f"Replied to {comment['username']} -> {reply} | {result}")

if __name__ == "__main__":
    auto_reply()


  