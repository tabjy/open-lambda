import requests
import os, sys
from subprocess import run
import time
import json

api_key = None
boss_port = None

def read_json(path):
    with open(path) as f:
        return json.load(f)

def write_json(path, data):
    with open(path, "w") as f:
        return json.dump(data, f, indent=2)

def boss_get(resource, check=True):
    url = f"http://localhost:{boss_port}/{resource}"
    resp = requests.get(url, headers={"api_key": api_key})
    if check:
        resp.raise_for_status()
    return resp

def boss_post(resource, data, check=True):
    url = f"http://localhost:{boss_port}/{resource}"
    resp = requests.post(url, headers={"api_key": api_key}, data=data)
    if check:
        resp.raise_for_status()
    return resp

def boss_invoke(lambda_name, data, check=True):
    url = f"http://localhost:{boss_port}/run/{lambda_name}"
    resp = requests.post(url, data=data)
    if check:
        resp.raise_for_status()
    return resp

def tester(platform):
    global api_key, boss_port
    print(f"Testing {platform}")

    # PART 1: config and launch

    # should create new config file
    run(["./ol", "new-boss"]).check_returncode()
    assert os.path.exists("default-boss-ol/config.json")

    # should have options platform (e.g., "aws", etc) and scaling ("manual" or "auto")
    config = read_json("default-boss-ol/config.json")
    assert "platform" in config
    assert "scaling" in config
    config["platform"] = platform
    config["scaling"] = "manual"
    write_json("default-boss-ol/config.json", config)

    # config should contain randomly generate secret API key
    assert "api_key" in config
    assert "boss_port" in config
    api_key = config["api_key"]
    boss_port = config["boss_port"]

    # should be able to start boss as background process
    run(["./ol", "boss", "--detach"]).check_returncode()

    # TODO: sleep, or check some other way it is ready?

    # PART 2: scaling

    # should start with zero workers
    status = boss_get("status").json()
    assert len(status["workers"]) == 0

    # start a worker (because we're chose "manual" scaling)
    boss_post("scaling/worker_count", 1)

    # there should be a worker, though probably not ready
    status = boss_get("status").json()
    assert len(status["workers"]) == 1

    # wait until it is ready (up to 3 minutes)
    t0 = t1 = time.time()
    while t1 - t0 < 180:
        time.sleep(1)
        status = boss_get("status").json()
        assert len(status["workers"]) == 1
        if status["workers"][0]["state"] == "ready":
            break
        t1 = time.time()

    # PART 3: registry
    
    lambda1_name = "hi"
    code = ["def f(event):", "\treturn 'hello'"]
    boss_post("registry/upload", {"name": lambda1_name, "code": "\n".join(code)})

    # PART 4: load balancing

    # does it forward the request to a worker and give us the proper response?
    result = boss_invoke(f"run/{lambda1_name}", None).json()
    assert result == 'hello'

    # if we should down all workers, do we get an error code back?
    boss_post("scaling/worker_count", 0)
    assert len(status["workers"]) == 0
    resp = boss_invoke(f"run/{lambda1_name}", None, check=False)
    assert resp.status_code != 200

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 boss-test.py (aws|azure|gcp) [platform2, ...]")

    for platform in sys.argv[1:]:
        tester(platform)


if __name__ == "__main__":
    main()