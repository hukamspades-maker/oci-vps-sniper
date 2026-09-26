import os
import time
import threading
import urllib.request
import urllib.parse
import json
import random
from flask import Flask, render_template_string
import oci.core
import oci.core.models as models

app = Flask(__name__)

status = {
    "attempts": 0,
    "last_attempt": "Never",
    "last_result": "Cloud sniper starting...",
    "success": False,
    "instance_id": None,
    "is_running": True,
    "public_ip": None
}

thread_started = False
thread_lock = threading.Lock()

BOT_KEYBOARD = {
    "keyboard": [
        [{"text": "📊 Status"}, {"text": "⏸️ Stop"}, {"text": "▶️ Start"}]
    ],
    "resize_keyboard": True
}

def send_telegram(message, reply_markup=None):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if token and chat_id:
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "Markdown"
            }
            if reply_markup:
                payload["reply_markup"] = json.dumps(reply_markup)
            data = urllib.parse.urlencode(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data)
            with urllib.request.urlopen(req, timeout=10) as r:
                print("Telegram notification sent successfully!")
        except Exception as e:
            print(f"Failed to send Telegram: {e}")

def telegram_listener_loop():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        return
    last_update_id = 0
    print("Telegram interactive listener started...")
    
    startup_msg = (
        "🟢 *OCI VPS Sniper Online & Ready!*\n\n"
        "• *Target:* Ubuntu 24.04 ARM (1 OCPU / 1 GB / 50 GB)\n"
        "• *Region:* ap-singapore-1\n"
        "• *Retry:* Every 35-55s with random jitter\n\n"
        "🎮 *Control Buttons:* Use the buttons below to Check Status, Pause, or Resume hunting anytime!"
    )
    send_telegram(startup_msg, reply_markup=BOT_KEYBOARD)

    while True:
        try:
            url = f"https://api.telegram.org/bot{token}/getUpdates?offset={last_update_id + 1}&timeout=15"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=20) as r:
                res = json.loads(r.read().decode("utf-8"))
                for update in res.get("result", []):
                    update_id = update.get("update_id", 0)
                    if update_id > last_update_id:
                        last_update_id = update_id
                    
                    msg = update.get("message", {})
                    chat = msg.get("chat", {})
                    sender_chat_id = chat.get("id")
                    text = msg.get("text", "").strip()
                    
                    if sender_chat_id and text:
                        cmd = text.strip().lower()
                        
                        if any(k in cmd for k in ["stop", "pause", "⏸"]):
                            status["is_running"] = False
                            status["last_result"] = "Paused by user via Telegram (/start to resume)"
                            reply = (
                                "⏸️ *OCI VPS Sniper Paused!*\n\n"
                                f"• *Total Attempts:* `{status.get('attempts', 0)}`\n"
                                "• *State:* Sleeping (no requests being sent to Oracle)\n\n"
                                "Tap *▶️ Start* or send `/start` anytime to resume hunting!"
                            )
                            send_telegram(reply, reply_markup=BOT_KEYBOARD)

                        elif any(k in cmd for k in ["start", "resume", "▶", "run"]):
                            status["is_running"] = True
                            status["last_result"] = "Resumed by user via Telegram"
                            reply = (
                                "▶️ *OCI VPS Sniper Resumed!*\n\n"
                                "• *Target:* Ubuntu 24.04 ARM (1 OCPU / 1 GB / 50 GB)\n"
                                "• *Region:* ap-singapore-1\n"
                                f"• *Attempts so far:* `{status.get('attempts', 0)}`\n\n"
                                "Actively hunting in Singapore! Tap *⏸️ Stop* to pause anytime."
                            )
                            send_telegram(reply, reply_markup=BOT_KEYBOARD)

                        else:
                            state_str = "🟢 Active (Hunting)" if status.get("is_running", True) else "⏸️ Paused"
                            now_str = status.get("last_attempt", "Initializing...")
                            attempts = status.get("attempts", 0)
                            last_res = status.get("last_result", "Hunting...")
                            reply = (
                                "🤖 *OCI VPS Sniper Status*\n\n"
                                f"• *State:* {state_str}\n"
                                f"• *Current Status:* {last_res}\n"
                                f"• *Total Attempts:* `{attempts}`\n"
                                f"• *Target:* Ubuntu 24.04 ARM (1 OCPU / 1 GB / 50 GB)\n"
                                f"• *Last Attempt:* {now_str}\n\n"
                                "Use the buttons below to control:"
                            )
                            send_telegram(reply, reply_markup=BOT_KEYBOARD)
        except Exception as e:
            time.sleep(5)

def sniper_loop():
    print("Starting OCI Sniper Loop inside worker...")
    status["last_result"] = "Connecting to Oracle Cloud API..."
    
    user_ocid = os.environ.get("OCI_USER")
    tenancy_ocid = os.environ.get("OCI_TENANCY")
    fingerprint = os.environ.get("OCI_FINGERPRINT")
    region = os.environ.get("OCI_REGION", "ap-singapore-1")
    private_key = os.environ.get("OCI_KEY_CONTENT", "").replace("\\n", "\n")

    if not (user_ocid and tenancy_ocid and fingerprint and private_key):
        status["last_result"] = "Error: Missing OCI environment variables!"
        print(status["last_result"])
        return

    config = {
        "user": user_ocid.strip(),
        "fingerprint": fingerprint.strip(),
        "key_content": private_key.strip(),
        "tenancy": tenancy_ocid.strip(),
        "region": region.strip()
    }

    try:
        compute_client = oci.core.ComputeClient(config)
        network_client = oci.core.VirtualNetworkClient(config)
        print("OCI Clients initialized successfully!")
    except Exception as e:
        status["last_result"] = f"Configuration Error: {str(e)}"
        print(status["last_result"])
        return

    compartment_id = os.environ.get("OCI_COMPARTMENT_ID", tenancy_ocid).strip()
    ad = os.environ.get("OCI_AD", "NqeN:AP-SINGAPORE-1-AD-1").strip()
    subnet_id = os.environ.get("OCI_SUBNET_ID", "").strip()
    image_id = os.environ.get("OCI_IMAGE_ID", "").strip()
    ssh_public_key = os.environ.get("OCI_SSH_PUBLIC_KEY", "").replace("\\n", "\n").strip()

    shape_config = models.LaunchInstanceShapeConfigDetails(
        ocpus=1.0,
        memory_in_gbs=1.0
    )

    launch_details = models.LaunchInstanceDetails(
        display_name="ubuntu24-ampere-1cpu-1gb",
        compartment_id=compartment_id,
        availability_domain=ad,
        shape="VM.Standard.A1.Flex",
        shape_config=shape_config,
        source_details=models.InstanceSourceViaImageDetails(
            image_id=image_id,
            boot_volume_size_in_gbs=50
        ),
        create_vnic_details=models.CreateVnicDetails(
            subnet_id=subnet_id,
            assign_public_ip=True
        ),
        metadata={
            "ssh_authorized_keys": ssh_public_key
        }
    )

    BASE_INTERVAL = 35
    MAX_JITTER = 20
    consecutive_429 = 0

    while not status["success"]:
        if not status.get("is_running", True):
            time.sleep(3)
            continue

        status["attempts"] += 1
        now_str = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
        status["last_attempt"] = now_str
        print(f"[{now_str}] Attempt #{status['attempts']}: Requesting instance...")

        try:
            res = compute_client.launch_instance(launch_details)
            status["success"] = True
            status["instance_id"] = res.data.id
            status["last_result"] = "SUCCESS! Instance created."
            print(">>> SUCCESS! Instance provisioned.")

            # Try to get the public IP
            public_ip = "Pending..."
            try:
                time.sleep(15)
                vnic_attachments = compute_client.list_vnic_attachments(
                    compartment_id=compartment_id,
                    instance_id=res.data.id
                ).data
                if vnic_attachments:
                    vnic = network_client.get_vnic(vnic_attachments[0].vnic_id).data
                    public_ip = vnic.public_ip or "No public IP"
                    status["public_ip"] = public_ip
            except Exception:
                public_ip = "Check Oracle Console"

            tg_msg = (
                "🎉 *SUCCESS! Oracle Cloud VPS Provisioned!* 🎉\n\n"
                "• *Instance Name:* ubuntu24-ampere-1cpu-1gb\n"
                "• *Shape:* VM.Standard.A1.Flex (1 OCPU / 1 GB RAM / 50 GB Disk)\n"
                "• *Region:* ap-singapore-1\n"
                f"• *Instance ID:* `{res.data.id}`\n"
                f"• *Public IP:* `{public_ip}`\n\n"
                "✅ *Sniper stopped automatically.*\n\n"
                f"🔑 *Connect:* `ssh -i oracle_vps_id_rsa ubuntu@{public_ip}`\n\n"
                "💡 *Tip:* You can resize up to 4 OCPU / 24 GB in the Oracle Console anytime."
            )
            send_telegram(tg_msg)
            break

        except oci.exceptions.ServiceError as e:
            if "Out of host capacity" in e.message or e.status == 500:
                consecutive_429 = 0
                status["last_result"] = f"Out of host capacity (Attempt #{status['attempts']})"
            elif e.status == 429:
                consecutive_429 += 1
                backoff = min(45 + (consecutive_429 * 15), 120)
                status["last_result"] = f"Rate limited (Backing off {backoff}s)"
                time.sleep(backoff)
            elif "LimitExceeded" in str(e.code) or "quota" in e.message.lower():
                status["last_result"] = f"Quota/Limit Error: {e.message}"
                send_telegram(f"⚠️ *Quota Error:* {e.message}\n\nSniper continues but this may need manual fix.", reply_markup=BOT_KEYBOARD)
            else:
                status["last_result"] = f"Error ({e.status}): {e.message[:100]}"
            print(f"[{now_str}] {status['last_result']}")
        except Exception as e:
            status["last_result"] = f"Unexpected Error: {str(e)[:100]}"
            print(f"[{now_str}] {status['last_result']}")

        # Notify every 50 attempts
        if status["attempts"] % 50 == 0:
            update_msg = (
                f"⏳ *OCI Sniper Update (Attempt #{status['attempts']})*\n\n"
                f"• *Status:* {status['last_result']}\n"
                f"• *Target:* 1 OCPU / 1 GB / 50 GB - Singapore\n"
                f"• *Last Try:* {now_str}\n\n"
                "Still hunting 24/7! 🎯"
            )
            send_telegram(update_msg, reply_markup=BOT_KEYBOARD)

        # Random jitter: 35-55 seconds between attempts
        jitter = random.randint(0, MAX_JITTER)
        time.sleep(BASE_INTERVAL + jitter)

@app.before_request
def start_sniper():
    global thread_started
    with thread_lock:
        if not thread_started:
            thread_started = True
            threading.Thread(target=sniper_loop, daemon=True).start()
            threading.Thread(target=telegram_listener_loop, daemon=True).start()

@app.route("/")
@app.route("/health")
def index():
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>OCI VPS Sniper</title>
        <meta http-equiv="refresh" content="30">
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #f8fafc; padding: 40px; }
            .card { background: #1e293b; padding: 25px; border-radius: 12px; max-width: 600px; margin: auto; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.3); }
            h2 { margin-top: 0; color: #38bdf8; }
            .badge { display: inline-block; padding: 6px 12px; border-radius: 9999px; font-weight: bold; }
            .running { background: #ca8a04; color: #fef08a; }
            .paused { background: #991b1b; color: #fecaca; }
            .success { background: #16a34a; color: #bbf7d0; }
        </style>
    </head>
    <body>
        <div class="card">
            <h2>Oracle Cloud Free Tier VPS Sniper</h2>
            <p><strong>Target:</strong> Ubuntu 24.04 ARM (1 OCPU / 1 GB RAM / 50 GB Disk) - Singapore</p>
            <p><strong>Total Attempts:</strong> {{ attempts }}</p>
            <p><strong>Last Attempt:</strong> {{ last_attempt }}</p>
            <p><strong>Status:</strong> <span class="badge {{ 'success' if success else ('running' if is_running else 'paused') }}">{{ last_result }}</span></p>
            {% if instance_id %}
                <h3 style="color: #4ade80;">Instance Created!</h3>
                <p><code>{{ instance_id }}</code></p>
                {% if public_ip %}<p><strong>Public IP:</strong> <code>{{ public_ip }}</code></p>{% endif %}
            {% endif %}
        </div>
    </body>
    </html>
    """
    return render_template_string(html, **status)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
