import os


class ControllerConfig:
    def __init__(self):
        self.controller_id = os.environ.get("FIREWALL_CONTROLLER_ID", "restricted-mock-controller")
        self.controller_version = os.environ.get("FIREWALL_CONTROLLER_VERSION", "0.1.0")
        self.allow_broker_only = True
        self.require_authorization = True
        self.audit_enabled = True
