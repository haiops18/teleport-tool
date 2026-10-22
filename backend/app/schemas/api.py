import re
from pydantic import BaseModel, Field, field_validator
class LoginRequest(BaseModel):
    proxy: str = Field(pattern=r'^[A-Za-z0-9._:-]+$')
    tsh_version: str
    username: str = Field(min_length=1,max_length=255)
    password: str = Field(min_length=1)
    otp: str|None = Field(default=None,max_length=32)
class ScanRequest(BaseModel): node_ids: list[int] = []
class ComputeDiscoveryRequest(BaseModel):
    node_ids: list[int] = Field(min_length=1,max_length=500)
    job_name: str|None = Field(default=None,max_length=150)

    @field_validator('job_name')
    @classmethod
    def validate_job_name(cls, value):
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if re.search(r'[\x00-\x1f\x7f]', value):
            raise ValueError('JOB_NAME_CONTAINS_CONTROL_CHARACTERS')
        return value
class ServiceConfigRequest(BaseModel):
    node_ids: list[int] = Field(min_length=1,max_length=100)
    method: str = 'override'
    restart_after_apply: bool = False
    job_name: str|None = Field(default=None,max_length=150)
class ReportExportRequest(BaseModel):
    node_ids: list[int] = Field(min_length=1,max_length=500)
class ReportRemoveRequest(BaseModel):
    node_ids: list[int] = Field(min_length=1,max_length=500)
