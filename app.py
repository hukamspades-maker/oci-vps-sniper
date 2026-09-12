import os
import time
import threading
import urllib.request
import urllib.parse
import json
from flask import Flask, render_template_string
import oci.core
import oci.core.models as models

app = Flask(__name__)

status = {
    "attempts": 0,
    "last_attempt": "Never",
    "last_result": "Cloud sniper starting...",
    "success": False,
    "instance_id": None
}

thread_started = False
thread_lock = threading.Lock()

def send_telegram(message):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if token and chat_id:
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            data = urllib.parse.urlencode({
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "Markdown"
            }).encode("utf-8")
            req = urllib.request.Request(url, data=data)
            with urllib.request.urlopen(req, timeout=10) as r:
                print("Telegram notification sent successfully!")
        except Exception as e:
            print(f"Failed to send Telegram: {e}")

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
        print("OCI Compute Client initialized successfully!")
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
        memory_in_gbs=6.0
    )

    launch_details = models.LaunchInstanceDetails(
        display_name="ubuntu24-ampere-1cpu-6gb",
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

    INTERVAL = 65

    while not status["success"]:
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

            # Send Final Victory Telegram Alert
            tg_msg = (
                "🎉 *SUCCESS! Oracle Cloud VPS Provisioned!* 🎉\n\n"
                "• *Instance Name:* ubuntu24-ampere-1cpu-6gb\n"
                "• *Shape:* VM.Standard.A1.Flex (1 OCPU / 6 GB RAM)\n"
                "• *Region:* ap-singapore-1\n"
                f"• *Instance ID:* `{res.data.id}`\n\n"
                "✅ *Sniper stopped automatically.* You can now connect via SSH with your key in `Desktop\\Oracle_VPS_Keys_Backup`!\n\n"
                "💡 *Tip:* You can easily resize it up to 2-4 OCPU / 12-24 GB in the Oracle Console anytime later."
            )
            send_telegram(tg_msg)
            break

        except oci.exceptions.ServiceError as e:
            if "Out of host capacity" in e.message or e.status == 500:
                status["last_result"] = "Out of host capacity (Retrying in 65s)"
            elif e.status == 429:
                status["last_result"] = "Rate limited (Backing off 45s)"
                time.sleep(45)
            else:
                status["last_result"] = f"Error: {e.message}"
            print(f"[{now_str}] {status['last_result']}")
        except Exception as e:
            status["last_result"] = f"Unexpected Error: {str(e)}"
            print(f"[{now_str}] {status['last_result']}")

        # Notify every 20 attempts
        if status["attempts"] % 20 == 0:
            update_msg = (
                f"⏳ *OCI Sniper Live Update (Attempt #{status['attempts']})*\n\n"
                f"• *Status:* {status['last_result']}\n"
                f"• *Target:* Ubuntu 24.04 ARM (1 OCPU / 6 GB RAM)\n"
                f"• *Last Attempt:* {now_str}\n\n"
                "Still actively hunting in the cloud 24/7!"
            )
            send_telegram(update_msg)

        time.sleep(INTERVAL)

@app.before_request
def start_sniper():
    global thread_started
    with thread_lock:
        if not thread_started:
            thread_started = True
            threading.Thread(target=sniper_loop, daemon=True).start()

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
            .success { background: #16a34a; color: #bbf7d0; }
        </style>
    </head>
    <body>
        <div class="card">
            <h2>Oracle Cloud Free Tier VPS Sniper</h2>
            <p><strong>Target:</strong> Ubuntu 24.04 ARM (1 OCPU / 6 GB RAM) - Singapore</p>
            <p><strong>Total Attempts:</strong> {{ attempts }}</p>
            <p><strong>Last Attempt:</strong> {{ last_attempt }}</p>
            <p><strong>Status:</strong> <span class="badge {{ 'success' if success else 'running' }}">{{ last_result }}</span></p>
            {% if instance_id %}
                <h3 style="color: #4ade80;">Instance Created!</h3>
                <p><code>{{ instance_id }}</code></p>
            {% endif %}
        </div>
    </body>
    </html>
    """
    return render_template_string(html, **status)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
