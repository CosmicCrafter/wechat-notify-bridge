"""Proxy management is accessible only with the existing administrator credential."""
from typing import Annotated
from fastapi import Depends
from pydantic import BaseModel, ConfigDict, Field, StrictBool


class ProxySettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    subscription_url: str | None = Field(default=None, max_length=4096)
    enabled: StrictBool
    update_interval: Annotated[int, Field(strict=True, ge=300, le=604800)]
    check_interval: Annotated[int, Field(strict=True, ge=30, le=3600)]
    priorities: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(max_length=8)


class ProxySelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str | None = Field(default=None, min_length=1, max_length=160)


def mount_proxy(app, authorize_admin):
    @app.get('/admin/api/proxy', dependencies=[Depends(authorize_admin)], include_in_schema=False)
    async def proxy_status():
        return app.state.proxy.snapshot()

    @app.post('/admin/api/proxy/config', dependencies=[Depends(authorize_admin)], include_in_schema=False)
    async def proxy_config(body: ProxySettings):
        return app.state.proxy.save(body)

    @app.post('/admin/api/proxy/update', dependencies=[Depends(authorize_admin)], include_in_schema=False)
    async def proxy_update():
        return app.state.proxy.action('update')

    @app.post('/admin/api/proxy/check', dependencies=[Depends(authorize_admin)], include_in_schema=False)
    async def proxy_check():
        return app.state.proxy.action('check')

    @app.post('/admin/api/proxy/select', dependencies=[Depends(authorize_admin)], include_in_schema=False)
    async def proxy_select(body: ProxySelection):
        return app.state.proxy.action('select', body.name)
