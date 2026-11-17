import csv
import json
import os
import statistics
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"

def read_env():
    values = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    return values

ENV = read_env()

BASE_URL = os.getenv(
    "OLLAMA_BASE_URL",
    ENV.get("OLLAMA_BASE_URL", "http://localhost:11434")
).rstrip("/")

MODEL = os.getenv(
    "OLLAMA_MODEL",
    ENV.get("OLLAMA_MODEL", "qwen2.5:7b")
)

REPEATS = 3
OUTPUT_TOKENS = 256
TEMPERATURE = 0
SEED = 42

# The same 7K prompt is tested on both context sizes.
TESTS = [
    {"name": "A_8K", "context": 8192, "target": 7000},
    {"name": "B_16K", "context": 16384, "target": 7000},
    {"name": "C_16K_11K", "context": 16384, "target": 11000},
    {"name": "D_16K_14K", "context": 16384, "target": 14000},
]

OUTPUT_DIR = BASE_DIR / "reports"
OUTPUT_DIR.mkdir(exist_ok=True)

# ============================================================
# ENVIRONMENT / RESOURCE MONITOR
# ============================================================

def get_ram_mb():
    """MemAvailable in WSL/Linux, not Windows host RAM."""
    try:
        data = Path("/proc/meminfo").read_text()
        for line in data.splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1024
    except Exception:
        pass
    return None


def get_gpu_memory():
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            values = [
                int(x.strip())
                for x in result.stdout.splitlines()
                if x.strip()
            ]
            return max(values) if values else None
    except Exception:
        pass
    return None


class ResourceMonitor:
    def __init__(self):
        self.running = False
        self.thread = None
        self.gpu_peak = None
        self.ram_min_available = None
        self.gpu_baseline = None
        self.ram_baseline = None

    def sample(self):
        gpu = get_gpu_memory()
        ram = get_ram_mb()

        if gpu is not None:
            self.gpu_peak = (
                gpu if self.gpu_peak is None
                else max(self.gpu_peak, gpu)
            )

        if ram is not None:
            self.ram_min_available = (
                ram if self.ram_min_available is None
                else min(self.ram_min_available, ram)
            )

    def worker(self):
        while self.running:
            self.sample()
            time.sleep(0.5)

    def start(self):
        self.gpu_baseline = get_gpu_memory()
        self.ram_baseline = get_ram_mb()

        self.gpu_peak = self.gpu_baseline
        self.ram_min_available = self.ram_baseline

        self.running = True
        self.thread = threading.Thread(
            target=self.worker,
            daemon=True,
        )
        self.thread.start()

    def stop(self):
        self.running = False

        if self.thread:
            self.thread.join(timeout=3)

        self.sample()

        return {
            "gpu_baseline_mb": self.gpu_baseline,
            "gpu_peak_mb": self.gpu_peak,
            "gpu_increase_mb": (
                self.gpu_peak - self.gpu_baseline
                if self.gpu_peak is not None
                and self.gpu_baseline is not None
                else None
            ),
            "ram_available_before_mb": self.ram_baseline,
            "ram_min_available_mb": self.ram_min_available,
            "ram_available_drop_mb": (
                self.ram_baseline - self.ram_min_available
                if self.ram_baseline is not None
                and self.ram_min_available is not None
                else None
            ),
        }


# ============================================================
# OLLAMA CLIENT
# ============================================================

def ollama_request(endpoint, payload=None, timeout=900):
    data = None

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    request = Request(
        f"{BASE_URL}{endpoint}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Ollama HTTP {exc.code}: {detail}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(
            f"Cannot connect to Ollama: {exc}"
        ) from exc


def check_ollama():
    print(f"Model: {MODEL}")
    print(f"Ollama URL: {BASE_URL}")

    data = ollama_request("/api/tags")

    models = [
        item["name"]
        for item in data.get("models", [])
    ]

    if not any(
        name == MODEL or name.startswith(MODEL + ":")
        for name in models
    ):
        raise RuntimeError(
            f"Model '{MODEL}' not found. Available: {models}"
        )

    print("Ollama connection: OK")


def generate(prompt, context_size, output_tokens):
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "keep_alive": "10m",
        "options": {
            "num_ctx": context_size,
            "num_predict": output_tokens,
            "temperature": TEMPERATURE,
            "seed": SEED,
        },
    }

    return ollama_request("/api/generate", payload)


# ============================================================
# SYNTHETIC SOC LOG GENERATOR
# ============================================================

HEADER = """
You are a SOC analyst working in a defensive cybersecurity environment.

Analyze the synthetic security logs below.

Identify:
1. Suspicious source IP addresses.
2. Repeated authentication failures.
3. Successful logins after failures.
4. Potential privilege escalation.
5. Evidence, inference, and unknown information separately.
6. Recommended investigation steps.

Do not invent evidence.
Do not assume that a successful login is malicious.
Explain the limitations of the available evidence.

SECURITY EVENT DATA:
"""


def make_prompt(event_count):
    logs = []

    for i in range(event_count):
        ip = f"192.0.2.{(i % 200) + 1}"
        event = i % 10
        second = i % 60

        if event < 6:
            line = (
                f"event_id={i} "
                f"timestamp=2026-11-17T10:15:{second:02d}Z "
                f"source_ip={ip} user=admin "
                f"action=login result=failed "
                f"service=ssh port=22 severity=medium "
                f"host=srv-{i % 5}"
            )
        elif event < 8:
            line = (
                f"event_id={i} "
                f"timestamp=2026-11-17T10:16:{second:02d}Z "
                f"source_ip={ip} user=ubuntu "
                f"action=login result=success "
                f"service=ssh port=22 severity=high "
                f"host=srv-{i % 5}"
            )
        else:
            line = (
                f"event_id={i} "
                f"timestamp=2026-11-17T10:17:{second:02d}Z "
                f"source_ip={ip} user=ubuntu "
                f"action=sudo result=success "
                f"command=systemctl service=ssh "
                f"severity=high host=srv-{i % 5}"
            )

        logs.append(line)

    return HEADER + "\n".join(logs)


# ============================================================
# PROMPT TOKEN CALIBRATION
# ============================================================

def calibrate_prompt(target_tokens):
    """
    Use Ollama prompt_eval_count to estimate the number
    of synthetic events needed to reach the target.
    Calibration calls are excluded from benchmark results.
    """

    event_count = max(1, target_tokens // 20)
    best_prompt = None
    best_count = 0

    print(f"\nCalibrating target: {target_tokens:,} tokens")

    for attempt in range(8):
        prompt = make_prompt(event_count)

        result = generate(
            prompt,
            context_size=16384,
            output_tokens=1,
        )

        actual = result.get("prompt_eval_count", 0)

        if actual <= 0:
            raise RuntimeError(
                "Missing prompt_eval_count from Ollama."
            )

        if (
            best_prompt is None
            or abs(actual - target_tokens)
            < abs(best_count - target_tokens)
        ):
            best_prompt = prompt
            best_count = actual

        print(
            f"  Attempt {attempt + 1}: "
            f"{actual:,} tokens"
        )

        if abs(actual - target_tokens) / target_tokens <= 0.01:
            break

        event_count = max(
            1,
            round(event_count * target_tokens / actual),
        )

    return best_prompt, best_count


# ============================================================
# BENCHMARK RUN
# ============================================================

def benchmark_once(test, prompt, run_number):
    monitor = ResourceMonitor()
    monitor.start()

    start = time.perf_counter()

    try:
        result = generate(
            prompt,
            context_size=test["context"],
            output_tokens=OUTPUT_TOKENS,
        )
    finally:
        wall_seconds = time.perf_counter() - start
        resources = monitor.stop()

    prompt_tokens = result.get("prompt_eval_count", 0)
    output_tokens = result.get("eval_count", 0)

    prompt_duration_ns = result.get(
        "prompt_eval_duration", 0
    )
    generation_duration_ns = result.get(
        "eval_duration", 0
    )
    load_duration_ns = result.get(
        "load_duration", 0
    )

    prompt_seconds = prompt_duration_ns / 1e9
    generation_seconds = generation_duration_ns / 1e9

    return {
        "test": test["name"],
        "context_size": test["context"],
        "target_prompt_tokens": test["target"],
        "run": run_number,
        "wall_seconds": round(wall_seconds, 4),
        "prompt_tokens": prompt_tokens,
        "output_tokens": output_tokens,
        "prompt_eval_seconds": round(prompt_seconds, 4),
        "prompt_tok_s": round(
            prompt_tokens / prompt_seconds, 2
        ) if prompt_seconds else 0,
        "generation_seconds": round(generation_seconds, 4),
        "generation_tok_s": round(
            output_tokens / generation_seconds, 2
        ) if generation_seconds else 0,
        "load_seconds": round(
            load_duration_ns / 1e9, 4
        ),
        "done_reason": result.get("done_reason"),
        **resources,
    }


# ============================================================
# STATISTICS
# ============================================================

def average(values):
    values = [v for v in values if v is not None]
    return round(statistics.mean(values), 2) if values else None


def summarize(records):
    summary = []

    for test_name in dict.fromkeys(
        item["test"] for item in records
    ):
        group = [
            item for item in records
            if item["test"] == test_name
        ]

        wall = [x["wall_seconds"] for x in group]
        generation = [x["generation_tok_s"] for x in group]
        prompt_speed = [x["prompt_tok_s"] for x in group]

        summary.append({
            "test": test_name,
            "context_size": group[0]["context_size"],
            "target_prompt_tokens": group[0]["target_prompt_tokens"],
            "actual_prompt_tokens_avg": average(
                [x["prompt_tokens"] for x in group]
            ),
            "wall_avg_seconds": average(wall),
            "wall_median_seconds": round(
                statistics.median(wall), 2
            ),
            "wall_min_seconds": round(min(wall), 2),
            "wall_max_seconds": round(max(wall), 2),
            "wall_stdev_seconds": round(
                statistics.stdev(wall), 3
            ) if len(wall) > 1 else 0,
            "prompt_tok_s_avg": average(prompt_speed),
            "generation_tok_s_avg": average(generation),
            "generation_tok_s_stdev": round(
                statistics.stdev(generation), 2
            ) if len(generation) > 1 else 0,
            "gpu_peak_mb": max(
                (x["gpu_peak_mb"] for x in group
                 if x["gpu_peak_mb"] is not None),
                default=None,
            ),
            "gpu_increase_avg_mb": average(
                [x["gpu_increase_mb"] for x in group]
            ),
            "ram_available_min_mb": min(
                (x["ram_min_available_mb"] for x in group
                 if x["ram_min_available_mb"] is not None),
                default=None,
            ),
            "runs": len(group),
        })

    return summary


# ============================================================
# MAIN
# ============================================================

def main():
    check_ollama()

    print("\n===== GPU / RAM BASELINE =====")
    print(f"GPU memory: {get_gpu_memory()} MB")
    print(f"WSL RAM available: {get_ram_mb()} MB")

    print("\n===== WARM-UP =====")
    generate(
        "Explain the difference between IDS and IPS.",
        context_size=16384,
        output_tokens=32,
    )
    print("Warm-up completed.")

    # Calibrate prompts once. Reuse the exact same prompt
    # for the 8K vs 16K comparison.
    prompt_7k, actual_7k = calibrate_prompt(7000)
    prompt_11k, actual_11k = calibrate_prompt(11000)
    prompt_14k, actual_14k = calibrate_prompt(14000)

    prompts = {
        "A_8K": prompt_7k,
        "B_16K": prompt_7k,
        "C_16K_11K": prompt_11k,
        "D_16K_14K": prompt_14k,
    }

    calibrated = {
        "7000": actual_7k,
        "11000": actual_11k,
        "14000": actual_14k,
    }

    all_records = []

    for test in TESTS:
        print("\n" + "=" * 65)
        print(
            f"{test['name']} | "
            f"Context={test['context']:,} | "
            f"Target={test['target']:,}"
        )
        print("=" * 65)

        prompt = prompts[test["name"]]

        for run_number in range(1, REPEATS + 1):
            record = benchmark_once(
                test,
                prompt,
                run_number,
            )
            all_records.append(record)

            print(
                f"Run {run_number}/{REPEATS} | "
                f"Prompt={record['prompt_tokens']:,} | "
                f"Output={record['output_tokens']} | "
                f"Wall={record['wall_seconds']:.2f}s | "
                f"Prompt={record['prompt_tok_s']:.2f} tok/s | "
                f"Generation={record['generation_tok_s']:.2f} tok/s | "
                f"GPU peak={record['gpu_peak_mb']} MB | "
                f"RAM available min={record['ram_min_available_mb']} MB"
            )

    summary = summarize(all_records)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_path = OUTPUT_DIR / (
        f"context_benchmark_{timestamp}.json"
    )
    csv_path = OUTPUT_DIR / (
        f"context_benchmark_{timestamp}.csv"
    )

    output = {
        "metadata": {
            "model": MODEL,
            "ollama_url": BASE_URL,
            "output_tokens": OUTPUT_TOKENS,
            "temperature": TEMPERATURE,
            "seed": SEED,
            "repeats": REPEATS,
            "calibrated_prompt_tokens": calibrated,
            "ram_metric": "WSL MemAvailable, not Windows host RAM",
            "gpu_metric": "Whole GPU memory from nvidia-smi",
        },
        "summary": summary,
        "raw_results": all_records,
    }

    json_path.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    with csv_path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=all_records[0].keys(),
        )
        writer.writeheader()
        writer.writerows(all_records)

    print("\n" + "=" * 65)
    print("FINAL SUMMARY")
    print("=" * 65)

    for item in summary:
        print(
            f"\n{item['test']}"
            f"\n  Actual prompt: {item['actual_prompt_tokens_avg']} tokens"
            f"\n  Wall average: {item['wall_avg_seconds']}s"
            f"\n  Prompt speed: {item['prompt_tok_s_avg']} tok/s"
            f"\n  Generation speed: {item['generation_tok_s_avg']} tok/s"
            f"\n  GPU peak: {item['gpu_peak_mb']} MB"
            f"\n  RAM available minimum: {item['ram_available_min_mb']} MB"
        )

    print("\nSaved:")
    print(json_path)
    print(csv_path)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nBenchmark interrupted.")
    except Exception as exc:
        print(f"\nBenchmark failed: {exc}")
        raise
