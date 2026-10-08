from monitoring import logs_indicate_expired_license, normalize_docker_status


# Bug caught: a normalizer that collapses live Docker states into "stopped".
def test_normalize_docker_status_preserves_running_and_restarting():
    assert normalize_docker_status("running") == "running"
    assert normalize_docker_status("restarting") == "restarting"


# Bug caught: a normalizer that leaks non-live Docker states instead of reporting "stopped".
def test_normalize_docker_status_maps_other_states_to_stopped():
    assert normalize_docker_status("exited") == "stopped"
    assert normalize_docker_status("paused") == "stopped"


# Bug caught: license detection that is case-sensitive or fails on Docker byte logs.
def test_license_message_is_case_insensitive_for_bytes_and_text():
    text = "THE DEFAULT LICENSE HAS EXPIRED. PLEASE USE THE LATEST SERVER VERSION."
    assert logs_indicate_expired_license(text)
    assert logs_indicate_expired_license(text.encode())
