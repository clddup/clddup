#!/usr/bin/env python3
"""Simulate contribution breakout, then export script-free animated SVGs."""

import argparse
from bisect import bisect_right
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

W, H = 1080, 330
LEFT, RIGHT, TOP, PADDLE_Y = 38, 1042, 109, 406
X, Y, STEP, SIZE = 63, 133, 18, 13
RADIUS, SPEED, DT = 5.5, 610, 1 / 180
LEVELS = {name: i for i, name in enumerate(("NONE", "FIRST_QUARTILE", "SECOND_QUARTILE", "THIRD_QUARTILE", "FOURTH_QUARTILE"))}
THEMES = {
    "dark": {"empty": "#161b22", "accent": "#27964e", "ball": "#ffd18a", "ramp": ["#01311f", "#034525", "#0f6d31", "#00c647"]},
    "light": {"empty": "#ebedf0", "accent": "#216e39", "ball": "#a45019", "ramp": ["#9be9a8", "#40c463", "#30a14e", "#216e39"]},
}


def simulate(calendar):
    bricks, days = [], []
    for wi, week in enumerate(calendar["weeks"]):
        for day in week["contributionDays"]:
            entry = dict(day, x=X + wi * STEP, y=Y + day["weekday"] * STEP)
            days.append(entry)
            if day["contributionCount"]:
                hp = LEVELS[day["contributionLevel"]]
                bricks.append(dict(entry, hp=hp, initial_hp=hp, hits=[], cleared=None))
    if not bricks:
        return {"bricks": [], "days": days, "frames": [], "scores": [(0.0, 0, 0)], "duration": 0, "cleared_at": 0, "hits": 0, "bounces": [], "wall_hits": 0}
    half_paddle, max_angle = 45, math.radians(78)
    field_left, field_right = LEFT + RADIUS, RIGHT - RADIUS
    field_width = field_right - field_left

    def reflected_x(value):
        position = (value - field_left) % (2 * field_width)
        return field_left + (position if position <= field_width else 2 * field_width - position)

    def paddle_plan(hit_x, last_angle):
        candidates = []
        for brick in bricks:
            if not brick['hp']:
                continue
            target_x = brick['x'] + SIZE/2 - field_left
            rise = PADDLE_Y - RADIUS - brick['y'] - SIZE/2
            # Mirrored targets describe genuine side-wall bounces, not homing.
            for tile in (-1, 0, 1):
                for direction in (-1, 1):
                    image_x = field_left + 2 * tile * field_width + direction * target_x
                    dx = image_x - hit_x
                    angle = math.atan2(dx, rise)
                    degrees = abs(math.degrees(angle))
                    if not 30 <= degrees <= 76:
                        continue
                    center = hit_x - angle/max_angle * half_paddle
                    if not LEFT+half_paddle <= center <= RIGHT-half_paddle:
                        continue
                    repeat_penalty = 45 if angle * last_angle > 0 else 0
                    cost = math.hypot(dx, rise) + abs(degrees-46)*3 + repeat_penalty
                    candidates.append((cost, center))
        if candidates:
            return min(candidates)[1]
        # Near a wall the paddle edge naturally sends the ball into that wall.
        offset = 30 if hit_x > (LEFT+RIGHT)/2 else -30
        return max(LEFT+half_paddle, min(hit_x-offset, RIGHT-half_paddle))

    first = max(bricks, key=lambda b: (b['y'], -abs(b['x'] - 540)))
    x, y = first['x'] + SIZE/2 - 80, 330.0
    vx, vy = SPEED*math.sin(math.radians(42)), -SPEED*math.cos(math.radians(42))
    paddle_x = max(LEFT+half_paddle, min(x, RIGHT-half_paddle))
    desired_paddle = paddle_x
    frames = [(0.0, x, y, paddle_x)]
    cleared, hits, collected, scores = 0, 0, 0, [(0.0, 0, 0)]
    bounces, wall_hits, last_angle = [], 0, 0
    t = 0.0
    for tick in range(1, 180 * 600):
        t = tick * DT
        if vy > 0 and tick % 6 == 1:
            fall_time = max(0, (PADDLE_Y-RADIUS-y)/vy)
            landing_x = reflected_x(x + vx*fall_time)
            desired_paddle = paddle_plan(landing_x, last_angle)
        paddle_x += max(-1800*DT, min(desired_paddle-paddle_x, 1800*DT))
        old_x, old_y = x, y
        x += vx * DT
        y += vy * DT
        collision = False
        if x < LEFT + RADIUS:
            x, vx, collision = LEFT + RADIUS, abs(vx), True
            wall_hits += 1
        elif x > RIGHT - RADIUS:
            x, vx, collision = RIGHT - RADIUS, -abs(vx), True
            wall_hits += 1
        if y < TOP + RADIUS:
            y, vy, collision = TOP + RADIUS, abs(vy), True
        if vy > 0 and y + RADIUS >= PADDLE_Y:
            assert abs(x-paddle_x) <= half_paddle+RADIUS, 'Predictive paddle missed the ball'
            y, collision = PADDLE_Y - RADIUS, True
            offset = max(-1, min(1, (x-paddle_x)/half_paddle))
            last_angle = offset * max_angle
            vx, vy = SPEED*math.sin(last_angle), -SPEED*math.cos(last_angle)
            bounces.append({'time':t, 'angle':math.degrees(last_angle), 'ball_x':x, 'paddle_x':paddle_x})
        for brick in bricks:
            if not brick["hp"]:
                continue
            bx, by = brick["x"], brick["y"]
            near_x = max(bx, min(x, bx + SIZE))
            near_y = max(by, min(y, by + SIZE))
            if (x-near_x)**2 + (y-near_y)**2 > RADIUS**2:
                continue
            if old_y + RADIUS <= by:
                y, vy = by - RADIUS - .01, -abs(vy)
            elif old_y - RADIUS >= by + SIZE:
                y, vy = by + SIZE + RADIUS + .01, abs(vy)
            elif old_x + RADIUS <= bx:
                x, vx = bx - RADIUS - .01, -abs(vx)
            elif old_x - RADIUS >= bx + SIZE:
                x, vx = bx + SIZE + RADIUS + .01, abs(vx)
            else:
                # Resolve a corner by the shallower penetration direction.
                if min(abs(x-bx), abs(x-bx-SIZE)) < min(abs(y-by), abs(y-by-SIZE)):
                    x, vx = (bx-RADIUS-.01, -abs(vx)) if x < bx+SIZE/2 else (bx+SIZE+RADIUS+.01, abs(vx))
                else:
                    y, vy = (by-RADIUS-.01, -abs(vy)) if y < by+SIZE/2 else (by+SIZE+RADIUS+.01, abs(vy))
            brick["hp"] -= 1
            brick["hits"].append(t)
            hits += 1
            if brick["hp"] == 0:
                brick["cleared"] = t
                cleared += 1
                collected += brick["contributionCount"]
                scores.append((t, cleared, collected))
            collision = True
            break
        if collision or tick % 6 == 0:
            frames.append((t, x, y, paddle_x))
        if cleared == len(bricks):
            frames.append((t + .2, x, y, paddle_x))
            frames.append((t + 4, x, y, paddle_x))
            break
    assert cleared == len(bricks), f"Simulation did not finish: {cleared}/{len(bricks)}"
    assert collected == calendar["totalContributions"]
    assert all(len(b["hits"]) == b["initial_hp"] for b in bricks)
    return {"bricks": bricks, "days": days, "frames": frames, "scores": scores, "duration": frames[-1][0], "cleared_at": t, "hits": hits, "bounces": bounces, "wall_hits": wall_hits}


def animate(attribute, values, times, duration, discrete=False):
    return (f'<animate attributeName="{attribute}" values="{";".join(map(str,values))}" '
            f'keyTimes="{";".join(f"{v/duration:.8f}" for v in times)}" dur="{duration:.5f}s" '
            f'calcMode="{"discrete" if discrete else "linear"}" repeatCount="indefinite"/>')


def css_timeline(source, prefix):
    """Use CSS keyframes so the exported SVG also animates in an img element."""
    namespace = 'http://www.w3.org/2000/svg'
    ET.register_namespace('', namespace)
    root = ET.fromstring(source)
    rules = []
    shared_tracks = {}
    index = 0
    for parent in list(root.iter()):
        tracks = [child for child in parent if child.tag == f'{{{namespace}}}animate']
        if not tracks:
            continue
        name = f'{prefix}-motion-{index}'
        index += 1
        duration = tracks[0].attrib['dur']
        attributes = {track.attrib['attributeName']: track for track in tracks}
        discrete = all(track.attrib.get('calcMode') == 'discrete' for track in tracks)
        if 'cx' in attributes:
            tx, ty = attributes['cx'], attributes['cy']
            times = tx.attrib['keyTimes'].split(';')
            values = [f'transform:translate({x}px,{y}px)' for x,y in zip(tx.attrib['values'].split(';'), ty.attrib['values'].split(';'))]
            parent.set('cx','0')
            parent.set('cy','0')
        elif 'x' in attributes:
            track = attributes['x']
            times = track.attrib['keyTimes'].split(';')
            values = [f'transform:translateX({value}px)' for value in track.attrib['values'].split(';')]
            parent.set('x','0')
        else:
            track = tracks[0]
            times = track.attrib['keyTimes'].split(';')
            values = [f'{track.attrib["attributeName"]}:{value}' for value in track.attrib['values'].split(';')]
        keyframes = ''.join(f'{float(time)*100:.6f}%{{{value}}}' for time,value in zip(times,values))
        signature = (keyframes, duration, discrete)
        if signature in shared_tracks:
            name = shared_tracks[signature]
        else:
            shared_tracks[signature] = name
            rules.append(f'@keyframes {name}{{{keyframes}}}')
        delay = parent.attrib.pop('data-trail-delay', '0')
        parent.set('style',parent.attrib.get('style','') + f';animation:{name} {duration} {"steps(1,end)" if discrete else "linear"} infinite;animation-delay:{delay}s')
        for track in tracks:
            parent.remove(track)
    style = ET.SubElement(root, f'{{{namespace}}}style')
    style.text = ''.join(rules)
    return ET.tostring(root, encoding='unicode')


def svg(game, theme, at=None):
    p, duration = THEMES[theme], game["duration"]
    prefix = f"breakout-{theme}"
    variables = ";".join(f"--{k}:{v}" for k,v in p.items() if k != "ramp")
    static = at is not None
    t = at or 0
    bricks = {b["date"]: b for b in game["bricks"]}
    output = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="GitHub 贡献打砖块动画" aria-describedby="{prefix}-desc" style="{variables}" data-duration="{duration:.5f}">',
              f'<desc id="{prefix}-desc">有贡献的日期变成砖块，球真实碰撞后砖块消失。颜色表示原始贡献等级，每个等级对应一到四点耐久。清场后循环。</desc>',
              f'<defs><filter id="{prefix}-glow" x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="3"/></filter></defs>',
              '<style>@media(prefers-reduced-motion:reduce){.moving{display:none}}</style>',
              '<g transform="translate(0 -96)">']
    for day in game["days"]:
        x,y = day["x"],day["y"]
        output.append(f'<rect x="{x}" y="{y}" width="{SIZE}" height="{SIZE}" rx="3.5" fill="var(--empty)" opacity=".3"/>')
        brick = bricks.get(day["date"])
        if brick is None:
            continue
        cleared_at = brick["cleared"]
        if static and cleared_at <= t:
            continue
        shades = list(reversed(p["ramp"][:brick["initial_hp"]]))
        damage = bisect_right(brick["hits"], t)
        output.append(f'<g class="brick" data-date="{day["date"]}" data-count="{day["contributionCount"]}" data-cleared-at="{cleared_at:.6f}"><rect x="{x}" y="{y}" width="{SIZE}" height="{SIZE}" rx="3.5" fill="{shades[damage]}">')
        if not static and len(shades) > 1:
            output.append(animate("fill", [*shades, shades[-1]], [0, *brick["hits"][:-1], duration], duration, True))
        output.append('</rect>')
        if not static:
            output.append(animate("visibility",["visible","hidden","hidden"],[0,cleared_at,duration],duration,True))
        output.append('</g>')
        if not static:
            for hit_at in brick["hits"]:
                output.append(f'<circle cx="{x+SIZE/2}" cy="{y+SIZE/2}" r="11" fill="none" stroke="var(--ball)" stroke-width="2" opacity="0">'+animate("opacity",[0,0,.9,0,0],[0,max(0,hit_at-.001),hit_at,hit_at+.12,duration],duration)+'</circle>')
    frames = game["frames"]
    if not frames:
        return ''.join(output) + '</g></svg>'
    times = [f[0] for f in frames]
    if static:
        index = max(0,bisect_right(times,t)-1)
        _,bx,by,px = frames[index]
    else:
        _,bx,by,px = frames[0]
    output.append(f'<rect class="moving paddle" x="{px-45:.2f}" y="{PADDLE_Y}" width="90" height="9" rx="4.5" fill="var(--accent)">')
    if not static:
        output.append(animate("x",[f'{f[3]-45:.2f}' for f in frames],times,duration))
    output.append('</rect>')
    for radius,opacity,blur,delay in ((2,.10,False,.14),(3,.17,False,.09),(4,.26,False,.045),(11,.3,True,0),(RADIUS,1,False,0)):
        if static and delay:
            continue
        output.append(f'<circle class="moving ball" cx="{bx:.2f}" cy="{by:.2f}" r="{radius}" fill="var(--ball)" opacity="{opacity}" data-trail-delay="{delay}"'+(f' filter="url(#{prefix}-glow)"' if blur else '')+'>')
        if not static:
            output.extend([animate("cx",[f'{f[1]:.2f}' for f in frames],times,duration),animate("cy",[f'{f[2]:.2f}' for f in frames],times,duration)])
        output.append('</circle>')
    output.extend(['</g>', '</svg>'])
    source = ''.join(output)
    return source if static else css_timeline(source, prefix)


def gallery(variants):
    document='''<!doctype html><html lang="zh-CN" data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>贡献打砖块预览</title><style>
    :root{color-scheme:dark;--surface:#0d1117;--ink:#e6edf3;--line:#30363d}:root[data-theme=light]{color-scheme:light;--surface:#fff;--ink:#1f2328;--line:#d8dee4}*{box-sizing:border-box}body{margin:0;background:var(--surface);color:var(--ink);font-family:system-ui,-apple-system,'Segoe UI',sans-serif}main{max-width:960px;padding:24px 12px;margin:auto}.toolbar{display:flex;gap:8px;flex-wrap:wrap;margin:0 4%}button,a{font:inherit;font-size:12px;padding:9px 14px;border:1px solid var(--line);border-radius:8px;background:var(--surface);color:var(--ink);cursor:pointer;text-decoration:none}button.active{border-color:var(--ink)}.board svg{display:block;width:100%;height:auto}.light{display:none}[data-theme=light] .light{display:block}[data-theme=light] .dark{display:none}
    </style></head><body><main><div class="toolbar"><button id="dark" class="active">深色</button><button id="light">浅色</button><button id="pause">暂停</button><button id="restart">重新开局</button><a id="download" href="breakout-dark.svg" download>下载 SVG</a></div><div class="board"><div class="dark">DARK_SVG</div><div class="light">LIGHT_SVG</div></div></main><script>
    const svgList=[...document.querySelectorAll('.board svg')];let paused=false;
    function current(){return document.querySelector('.board .'+document.documentElement.dataset.theme+' svg');}
    function animations(){return svgList.flatMap(svg=>svg.getAnimations({subtree:true}));}
    function time(){return (current().querySelector('.paddle')?.getAnimations()[0]?.currentTime||0)/1000;}
    function seek(seconds){for(const animation of animations()){animation.currentTime=seconds*1000;if(paused)animation.pause();}}
    for(const theme of ['dark','light'])document.getElementById(theme).onclick=()=>{const seconds=time();document.documentElement.dataset.theme=theme;current().getBoundingClientRect();seek(seconds);for(const id of ['dark','light'])document.getElementById(id).classList.toggle('active',id===theme);document.getElementById('download').href='breakout-'+theme+'.svg';};
    document.getElementById('pause').onclick=function(){paused=!paused;for(const animation of animations())paused?animation.pause():animation.play();this.textContent=paused?'继续':'暂停';};
    document.getElementById('restart').onclick=()=>seek(0);
    if(new URLSearchParams(location.search).get('theme')==='light')document.getElementById('light').click();
    </script></body></html>'''
    return document.replace('DARK_SVG',variants['dark']).replace('LIGHT_SVG',variants['light'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--images-only', action='store_true', help='Export only the two SVGs used by the profile')
    parser.add_argument('--playback-rate',type=float,default=.5,help='Playback rate relative to the original simulation (default: 0.5)')
    args=parser.parse_args()
    if not 0 < args.playback_rate <= 2:
        parser.error('--playback-rate must be greater than 0 and no more than 2')
    snapshot=json.loads(args.snapshot.read_text())
    calendar=snapshot['calendar']
    game=simulate(calendar)
    rate=args.playback_rate
    game['frames']=[(frame[0]/rate,*frame[1:]) for frame in game['frames']]
    game['scores']=[(score[0]/rate,*score[1:]) for score in game['scores']]
    for brick in game['bricks']:
        brick['hits']=[time/rate for time in brick['hits']]
        brick['cleared']/=rate
    for bounce in game['bounces']:
        bounce['time']/=rate
    game['duration']/=rate
    game['cleared_at']/=rate
    args.output.mkdir(parents=True,exist_ok=True)
    variants={}
    times={'start':0,'mid':game['scores'][len(game['scores'])//2][0]+.05,'end':game['cleared_at']+1}
    for theme in THEMES:
        variants[theme]=svg(game,theme)
        (args.output/f'breakout-{theme}.svg').write_text(variants[theme]+'\n', encoding='utf-8')
        if not args.images_only:
            for name,at in times.items():
                (args.output/f'breakout-{theme}-{name}.svg').write_text(svg(game,theme,at)+'\n', encoding='utf-8')
    if args.images_only:
        print(f'{len(game["bricks"])} bricks · {calendar["totalContributions"]} contributions · {args.output}')
        return
    (args.output/'breakout.html').write_text(gallery(variants))
    (args.output/'breakout-events.json').write_text(json.dumps({'duration':game['duration'],'hits':game['hits'],'scores':game['scores'],'bricks':game['bricks'],'bounces':game['bounces'],'wall_hits':game['wall_hits']},ensure_ascii=False,indent=2)+'\n')
    print(f'{len(game["bricks"])} bricks, {game["hits"]} real collisions, {game["duration"]:.2f} seconds, {calendar["totalContributions"]} contributions collected.')
    print(args.output/'breakout.html')


if __name__=='__main__':
    main()
