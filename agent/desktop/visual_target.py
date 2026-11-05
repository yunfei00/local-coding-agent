"""将本次授权模型图片坐标映射到同一窗口的物理客户区。"""
import math
import time
from agent.tools.base import ToolError

def coordinate_grid(image):
    """仅为已脱敏的模型缩略图增加坐标参照，原始截图保持不变。"""
    from PIL import ImageDraw
    result=image.copy();draw=ImageDraw.Draw(result)
    for value in range(0,1000,100):
        x=round(value*result.width/1000);y=round(value*result.height/1000)
        draw.line((x,0,x,result.height-1),fill=(155,155,155),width=1)
        draw.line((0,y,result.width-1,y),fill=(155,155,155),width=1)
        draw.rectangle((x+1,0,x+28,12),fill='white');draw.text((x+2,1),str(value),fill='black')
        draw.rectangle((0,y+1,28,y+13),fill='white');draw.text((1,y+2),str(value),fill='black')
    return result

def resolve_visual_point(arguments,receipt,*,owner,window_id,geometry,now=None):
    def fail(code,message):raise ToolError(code,message)
    if not receipt or receipt.get('owner')!=owner or receipt.get('window_id')!=window_id:
        fail('DESKTOP_CAPTURE_SCOPE','视觉回退需要当前任务、当前窗口的截图。')
    if not receipt.get('shared') or receipt.get('scope')!='window':
        fail('DESKTOP_IMAGE_NOT_SHARED','需要明确授权并发送给视觉模型的窗口图片，不能猜测坐标。')
    age=(time.time() if now is None else now)-receipt['captured_at']
    if not 0<=age<=120 or any(receipt.get(k)!=geometry.get(k) for k in ('client_size','dpi','client_origin')):
        fail('DESKTOP_CAPTURE_STALE','截图已过期或窗口移动/缩放；重新截图后定位。')
    x,y=arguments.get('x'),arguments.get('y');width,height=receipt['model_image_size']
    normalized=arguments.get('coordinate_space')=='normalized_1000'
    bounds=(0<=x<=1000 and 0<=y<=1000) if normalized and all(isinstance(v,int) for v in (x,y)) else (0<=x<width and 0<=y<height) if all(isinstance(v,int) for v in (x,y)) else False
    if any(isinstance(v,bool) or not isinstance(v,int) for v in (x,y)) or not bounds:
        fail('DESKTOP_COORDINATES_INVALID','坐标必须位于本次模型图片内。')
    original_width,original_height=receipt['image_size']
    if [original_width,original_height]!=geometry['client_size'] or min(width,height)<=0:
        fail('DESKTOP_CAPTURE_GEOMETRY_UNKNOWN','截图不是完整客户区，不能安全映射坐标。')
    if normalized:return min(original_width-1,math.floor(x*original_width/1000)),min(original_height-1,math.floor(y*original_height/1000))
    return min(original_width-1,math.floor((x+.5)*original_width/width)),min(original_height-1,math.floor((y+.5)*original_height/height))
