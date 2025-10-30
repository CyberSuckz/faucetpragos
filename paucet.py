from web3 import Web3
from eth_utils import to_hex
from eth_account import Account
from fake_useragent import FakeUserAgent
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading, requests, json, random, time, sys, os

RPC_URL = "https://atlantic.dplabs-internal.com/"
EXPLORER = "https://atlantic.pharosscan.xyz/tx/"

RECEPIENT = "0x8e23cb4af617dd008aa2b6901bc4c2df030bb617" # Paste Your EVM Recepient Address
API_KEY = "c14c6956458a2ee88c9bdce43dbfa389" # Paste Your CAPTCHA API KEY

# 2captcha.com
CAPTCHA_API = "https://api.2captcha.com" 

# Using capmonster.cloud? => "https://api.capmonster.cloud"

PAGE_URL = "https://faroswap.xyz/"
SITE_KEY = "6LcFofArAAAAAMUs2mWr4nxx0OMk6VygxXYeYKuO"

w3 = Web3(Web3.HTTPProvider(RPC_URL))

session = requests.Session()

Account.enable_unaudited_hdwallet_features()

print_lock = threading.Lock()

def safe_print(*args, **kwargs):
    with print_lock:
        print(*args, **kwargs)

def load_proxies(file_path="proxy.txt"):
    proxies = []
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            for line in f:
                proxy = line.strip()
                if proxy:
                    proxies.append(proxy)
    return proxies

def get_random_wallet(wallets):
    if not wallets:
        safe_print("❌ No wallets available!")
        return None
    return random.choice(wallets)

def get_random_proxy(proxies):
    if not proxies:
        return None
    proxy = random.choice(proxies)
    return {"http": proxy, "https": proxy}

def generate_evm_wallet():
    private_key = os.urandom(32).hex()
    acct = Account.from_key(bytes.fromhex(private_key))
    return private_key, acct.address

def solve_recaptcha(page_url, site_key, retries=5):
    for attempt in range(retries):
        try:
            if API_KEY is None:
                return None

            url = f"{CAPTCHA_API}/createTask"
            data = json.dumps({
                "clientKey": API_KEY,
                "task": {
                    "type": "RecaptchaV2TaskProxyless",
                    "websiteURL": page_url,
                    "websiteKey": site_key
                }
            })
            response = session.post(url=url, data=data)
            response.raise_for_status()
            result_text = response.text
            result_json = json.loads(result_text)

            if result_json.get("errorId") != 0:
                err_text = result_json.get("errorDescription", "Unknown Error")
                return {"success": False, "message": str(err_text)}

            request_id = result_json.get("taskId")

            for _ in range(30):
                res_url = f"{CAPTCHA_API}/getTaskResult"
                res_data = json.dumps({
                    "clientKey": API_KEY,
                    "taskId": request_id
                })

                res_response = session.post(url=res_url, data=res_data)
                res_response.raise_for_status()
                res_result_text = res_response.text
                res_result_json = json.loads(res_result_text)

                if res_result_json.get("status") == "ready":
                    recaptcha_token = res_result_json["solution"]["gRecaptchaResponse"]
                    return {"success": True, "message": recaptcha_token}
                
                elif res_result_json.get("status") == "processing":
                    time.sleep(5)
                    continue
                else:
                    break

        except (Exception, requests.RequestException) as e:
            if attempt < retries - 1:
                time.sleep(5)
                continue
            return {"success": False, "message": f"Network error → {str(e)[:50]}..."}

def request_faucet(address, recaptcha_token, proxies): 
    url = "https://api.dodoex.io/gas-faucet-server/faucet/claim"

    headers = {
        "Accept": "*/*",
        "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
        "Content-Type": "application/json",
        "Origin": "https://faroswap.xyz",
        "Referer": "https://faroswap.xyz/",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "cross-site",
        "User-Agent": FakeUserAgent().random
    }

    

    payload = {
        "chainId": 688689,
        "address": address,
        "recaptchaToken": recaptcha_token
    }

    proxy = get_random_proxy(proxies)

    try:
        response = session.post(url, json=payload, headers=headers, proxies=proxy, timeout=120)
        resp_json = response.json()

        if resp_json.get("code") == 0:
            return {"success": True, "message": resp_json.get("data").get("txHash")}
        else:
            return {"success": False, "message": resp_json.get("msg", "Unknown Error")}
    except requests.RequestException as e:
        return {"success": False, "message": f"Network error → {str(e)[:50]}..."}

def get_balance(address):
    balance_wei = w3.eth.get_balance(address)
    return w3.from_wei(balance_wei, "ether")

def send_all_balance(private_key, from_address, job_id=0, total_jobs=0, max_retries=5):
    job_prefix = f"[Job {job_id:2d}/{total_jobs}]" if job_id > 0 else ""
    
    for attempt in range(1, max_retries + 1):
        try:
            balance = w3.eth.get_balance(from_address)
            if balance == 0:
                return {"success": False, "message": "Balance 0"}

            gas_price = w3.eth.gas_price
            gas_limit = 21000
            fee = gas_price * gas_limit
            tx_value = balance - fee

            if tx_value <= 0:
                return {"success": False, "message": "Insufficient funds for gas"}

            nonce = w3.eth.get_transaction_count(from_address, 'pending')
            
            tx = {
                "nonce": nonce,
                "to": w3.to_checksum_address(RECEPIENT),
                "value": tx_value,
                "gas": gas_limit,
                "gasPrice": gas_price,
                "chainId": w3.eth.chain_id,
            }

            signed_tx = w3.eth.account.sign_transaction(tx, private_key)
            raw_tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            tx_hash = to_hex(raw_tx_hash)

            time.sleep(2)
            
            try:
                receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
                if receipt and receipt['status'] == 1:
                    return {"success": True, "tx_hash": tx_hash, "receipt": receipt}
                else:
                    safe_print(f"{job_prefix} ⚠️  Attempt {attempt}: Transaction failed (status=0)")
                    
            except Exception as receipt_error:
                safe_print(f"{job_prefix} ⚠️  Attempt {attempt}: Receipt error → {str(receipt_error)[:50]}...")
                return {"success": True, "tx_hash": tx_hash, "warning": "Could not verify transaction"}

        except Exception as e:
            error_msg = str(e).lower()
            
            if "insufficient funds" in error_msg:
                return {"success": False, "message": "Insufficient funds for gas"}
            elif "nonce too low" in error_msg:
                safe_print(f"{job_prefix} ⚠️  Attempt {attempt}: Nonce too low, retrying...")
                time.sleep(2)
                continue
            elif "replacement transaction underpriced" in error_msg:
                safe_print(f"{job_prefix} ⚠️  Attempt {attempt}: Transaction underpriced, retrying with higher gas...")
                time.sleep(2)
                continue
            elif "transaction not found" in error_msg:
                safe_print(f"{job_prefix} ⚠️  Attempt {attempt}: Transaction not found, retrying...")
                time.sleep(3)
                continue
            elif "network" in error_msg or "connection" in error_msg or "timeout" in error_msg:
                safe_print(f"{job_prefix} ⚠️  Attempt {attempt}: Network issue → {str(e)[:50]}...")
                time.sleep(random.randint(3, 6))
                continue
            else:
                safe_print(f"{job_prefix} ⚠️  Attempt {attempt}: Unexpected error → {str(e)[:50]}...")
                
        if attempt < max_retries:
            delay = random.randint(2, 5)
            safe_print(f"{job_prefix} ⏳ Retrying transfer in {delay} seconds...")
            time.sleep(delay)

    return {"success": False, "message": f"Transfer failed after {max_retries} attempts"}


def run_job(index, total_jobs, proxies):
    job_prefix = f"[Job {index:2d}/{total_jobs}]"
    
    safe_print(f"\n{job_prefix} 🚀 Starting job...")
    priv, addr = generate_evm_wallet()
    safe_print(f"{job_prefix} 🔑 From Address: {addr}")
    safe_print(f"{job_prefix} 🎯 To Address: {RECEPIENT}")

    recaptcha = solve_recaptcha(PAGE_URL, SITE_KEY)
    if recaptcha.get("success"):
        recaptcha_token = recaptcha.get("message")
        safe_print(f"{job_prefix} ✅ Recaptcha Solved")

        safe_print(f"{job_prefix} 💧 Requesting faucet...")
        result = request_faucet(addr, recaptcha_token, proxies)

        if result.get("success"):
            safe_print(f"{job_prefix} ✅ Faucet success → Explorer: {EXPLORER}{result.get('message')}")

            wait_time = 5
            safe_print(f"{job_prefix} ⏳ Waiting {wait_time}s to check balance...")
            time.sleep(wait_time)

            bal = 0
            for attempt in range(1, 6):
                bal = get_balance(addr)
                if bal > 0:
                    break
                safe_print(f"{job_prefix} ⚠️  Balance still 0 (attempt {attempt}/5), retrying in {wait_time}s...")
                time.sleep(wait_time)

            safe_print(f"{job_prefix} 💰 Balance: {bal:.6f} PHRS")

            if bal > 0:
                safe_print(f"{job_prefix} 📤 Transferring to {RECEPIENT}...")
                transfer_result = send_all_balance(priv, addr, index, total_jobs)
                
                if transfer_result["success"]:
                    safe_print(f"{job_prefix} 🎉 Faucet Transfered Successfully!")
                    safe_print(f"{job_prefix} 📝 Explorer: {EXPLORER}{transfer_result['tx_hash']}")
                    return True
                else:
                    safe_print(f"{job_prefix} ❌ Transfer Faucet failed: {transfer_result['message']}")
            else:
                safe_print(f"{job_prefix} ❌ Balance still 0 after 3 attempts, skipping transfer")
        else:
            safe_print(f"{job_prefix} ❌ Request Faucet FAILED: {result.get('message')}")
    else:
        safe_print(f"{job_prefix} ❌ Solve Recaptcha FAILED: {recaptcha.get('message')}")

    safe_print(f"{job_prefix} ❌ Job completed with failure")
    return False

if __name__ == "__main__":
    try:
        safe_print("\n" + "="*70)
        safe_print("           🚰 PHAROS ATLANTIC FAUCET AUTO BOT - VONSSY 🚰")
        safe_print("="*70)
        
        if not w3.is_connected():
            safe_print("❌ Failed to connect to RPC. Check network/RPC_URL.")
            exit(1)

        proxies = load_proxies("proxy.txt")
        
        safe_print(f"📋 Loaded {len(proxies)} proxies")

        total_runs = int(input("🔢 Enter number of loops: "))
        max_threads = int(input("🧵 Enter number of threads: "))

        safe_print(f"\n🚀 Starting {total_runs} jobs with {max_threads} threads...")
        safe_print("="*60)

        total_success = 0
        start_time = time.time()

        with ThreadPoolExecutor(max_workers=max_threads) as executor:
            futures = [executor.submit(run_job, i+1, total_runs, proxies) for i in range(total_runs)]
            
            completed = 0
            for future in as_completed(futures):
                completed += 1
                success = future.result()
                if success:
                    total_success += 1
                
                progress = (completed / total_runs) * 100
                safe_print(f"\n📊 Progress: {completed}/{total_runs} ({progress:.1f}%) | Success: {total_success}")

        end_time = time.time()
        duration = end_time - start_time

        rate = (total_success / total_runs * 100) if total_runs > 0 else 0

        safe_print("\n" + "="*60)
        safe_print("                    📊 FINAL SUMMARY")
        safe_print("="*60)
        safe_print(f"✅ Total Success    : {total_success}")
        safe_print(f"📢 Total Jobs       : {total_runs}")
        safe_print(f"❌ Failed Jobs      : {total_runs - total_success}")
        safe_print(f"📊 Success Rate     : {rate:.2f}%")
        safe_print(f"⏱️  Duration        : {duration:.2f} seconds")
        safe_print(f"⚡ Average per job  : {duration/total_runs:.2f} seconds")
        safe_print("="*60)

    except KeyboardInterrupt:
        safe_print("\n\n🛑 Keyboard Interrupt detected. Program stopped.")
        sys.exit(0)
