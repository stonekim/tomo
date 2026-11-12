"""Bound request memory before the JSON parser, including chunked requests."""
from fastapi.responses import JSONResponse


class RequestSizeLimit:
    def __init__(self, app, maximum=524288):
        self.app,self.maximum=app,maximum

    async def __call__(self, scope, receive, send):
        if scope['type']!='http' or scope['method'] not in ('POST','PUT','PATCH'):
            return await self.app(scope,receive,send)
        headers=dict(scope.get('headers',[]))
        try:length=int(headers.get(b'content-length',b'0'))
        except ValueError:length=-1
        if length<0 or length>self.maximum:
            return await JSONResponse(status_code=413,content={'error':{'code':'REQUEST_TOO_LARGE','message':'Request exceeds configured size'}})(scope,receive,send)
        body=bytearray();size=0
        while True:
            message=await receive()
            if message['type']=='http.disconnect':return
            size+=len(message.get('body',b''))
            if size>self.maximum:
                return await JSONResponse(status_code=413,content={'error':{'code':'REQUEST_TOO_LARGE','message':'Request exceeds configured size'}})(scope,receive,send)
            body.extend(message.get('body',b''))
            if not message.get('more_body'):break
        sent=False
        async def replay():
            nonlocal sent
            if not sent:
                sent=True
                return {'type':'http.request','body':bytes(body),'more_body':False}
            return await receive()
        await self.app(scope,replay,send)
