"""Deterministic world rules. Models may propose tools, never commit arbitrary state."""
from copy import deepcopy
import hashlib
import hmac
import json
import secrets

_TURN_SECRET = secrets.token_bytes(32)

def sign_payload(payload, context):
    raw = {"context": context, "payload": {k: v for k, v in payload.items() if k != "proof"}}
    return hmac.new(_TURN_SECRET, json.dumps(raw, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode(), hashlib.sha256).hexdigest()
from tomo.platform.errors import PlatformError

NPCS = ('mira', 'chen', 'lin')
NAMES = {'player': '你', 'mira': '米拉（搭档）', 'chen': '陈（招聘人）', 'lin': '林（老同事）'}
PLACES = {'office': '旧办公室', 'cafe': '街角咖啡馆', 'studio': '新工作室'}
ITEMS = {'notebook': '项目笔记', 'key': '工作室钥匙', 'coffee': '咖啡'}
GOALS = {'mira': '找一位愿意共同承担风险的搭档', 'chen': '让候选人了解新岗位的条件', 'lin': '确认旧团队能平稳交接'}
EDGES = {'office': ('cafe',), 'cafe': ('office', 'studio'), 'studio': ('cafe',)}
LIMIT = 8


def reject(message='This action contradicts the current world'):
    raise PlatformError(422, 'INVALID_GAME_ACTION', message)


def initial_state(scenario, engine='local'):
    return {'game_version': 1, 'scenario': scenario, 'engine': engine, 'turn': 0,
            'characters': {'player': 'office', 'mira': 'studio', 'chen': 'office', 'lin': 'cafe'},
            'items': {'notebook': 'location:office', 'key': 'location:studio', 'coffee': 'location:cafe'},
            'relationships': {n: 0 for n in NPCS}, 'learned': [], 'decision': None,
            'memories': {n: [] for n in NPCS}, 'ending': None}


def check_shape(state):
    if not isinstance(state, dict) or set(state) != set(initial_state('', 'local')):
        reject('Unknown or missing game state fields')
    if not isinstance(state['scenario'], str) or not 1 <= len(state['scenario'].strip()) <= 1200 or state['engine'] not in ('local', 'model'):
        reject('Invalid scenario or engine')
    if type(state['game_version']) is not int or state['game_version'] != 1:
        reject()
    if type(state['turn']) is not int or not 0 <= state['turn'] <= LIMIT:
        reject()
    if not isinstance(state['characters'], dict) or set(state['characters']) != set(NAMES) or any(not isinstance(v, str) or v not in PLACES for v in state['characters'].values()):
        reject()
    if not isinstance(state['items'], dict) or set(state['items']) != set(ITEMS) or any(v not in (*NAMES, *(f'location:{p}' for p in PLACES)) for v in state['items'].values()):
        reject()
    if not isinstance(state['relationships'], dict) or set(state['relationships']) != set(NPCS) or any(type(v) is not int or not 0 <= v <= 3 for v in state['relationships'].values()):
        reject()
    if not isinstance(state['learned'], list) or any(not isinstance(v, str) or v not in ITEMS for v in state['learned']) or len(set(state['learned'])) != len(state['learned']):
        reject()
    if state['decision'] not in (None, 'accept', 'stay'):
        reject()
    if not isinstance(state['memories'], dict) or set(state['memories']) != set(NPCS) or any(not isinstance(v, list) or len(v) > LIMIT or any(not isinstance(t, str) or len(t) > 280 for t in v) for v in state['memories'].values()):
        reject()
    if state['ending'] not in (None, 'stable_plan', 'collaborative_jump', 'solo_jump', 'undecided'):
        reject()


def action_shape(action, actor):
    if not isinstance(action, dict) or action.get('actor') != actor or action.get('action') not in ('move', 'talk', 'take', 'give', 'inspect', 'decide', 'wait', 'finish'):
        reject('Invalid actor or tool')
    allowed = {'move': {'destination'}, 'talk': {'target', 'text'}, 'take': {'item'}, 'give': {'item', 'target'},
               'inspect': {'item'}, 'decide': {'choice'}, 'wait': set(), 'finish': set()}[action['action']]
    if set(action) - {'actor', 'action'} - allowed:
        reject('Unexpected tool arguments')
    if actor != 'player' and action['action'] in ('inspect', 'decide', 'finish'):
        reject('NPC cannot choose on the player’s behalf')
    if 'text' in action and (not isinstance(action['text'], str) or len(action['text']) > 240):
        reject('Dialogue is too long')


def apply_tool(state, action):
    actor = action.get('actor')
    if not isinstance(actor, str) or actor not in NAMES:
        reject()
    action_shape(action, actor)
    kind = action['action']; place = state['characters'][actor]
    if kind == 'move':
        dest = action.get('destination')
        if dest not in EDGES[place]: reject('Move must use an adjacent location')
        state['characters'][actor] = dest
        return f'{NAMES[actor]}走到{PLACES[dest]}。'
    if kind == 'talk':
        target = action.get('target')
        if not isinstance(target, str) or target not in NAMES or target == actor or state['characters'][target] != place:
            reject('Conversation requires two people in the same place')
        if actor == 'player': state['relationships'][target] = min(3, state['relationships'][target] + 1)
        return f'{NAMES[actor]}与{NAMES[target]}交谈。'
    if kind in ('inspect', 'take', 'give'):
        item = action.get('item')
        if not isinstance(item, str) or item not in ITEMS: reject('Unknown item')
        holder = state['items'][item]
        if kind == 'give':
            target = action.get('target')
            if holder != actor or not isinstance(target, str) or target not in NAMES or target == actor or state['characters'][target] != place:
                reject('You must hold an item and meet its recipient before giving it')
            state['items'][item] = target
            return f'{NAMES[actor]}把{ITEMS[item]}交给{NAMES[target]}。'
        if holder not in (actor, 'location:' + place): reject('This item is not reachable')
        if kind == 'take':
            if holder == actor: reject('Already holding this item')
            state['items'][item] = actor
            return f'{NAMES[actor]}拿起{ITEMS[item]}。'
        if item not in state['learned']: state['learned'].append(item)
        return f'你查看了{ITEMS[item]}：' + {'notebook': '新项目尚缺一位合作伙伴，离职前也需要安排交接。', 'key': '新工作室能立即使用，但承诺需要自己承担。', 'coffee': '杯套上记着老同事希望与你聊一聊。'}[item]
    if kind == 'decide':
        if state['decision'] is not None or action.get('choice') not in ('accept', 'stay'):
            reject('Change a committed decision by forking before it, not by overwriting it')
        state['decision'] = action['choice']
        return '你决定' + ('接受新工作的邀请。' if state['decision'] == 'accept' else '留在当前岗位，并重新安排未来。')
    if kind == 'finish':
        if state['turn'] < 2: reject('Explore at least two turns before closing the chapter')
        return '你暂时停下脚步，整理这条人生分支。'
    return f'{NAMES[actor]}等待片刻。'


def transition(old, player, agents):
    check_shape(old)
    if old['ending']: reject('This branch has ended; fork an earlier point to play again')
    if not isinstance(agents, list) or len(agents) > 3 or any(not isinstance(a, dict) for a in agents): reject('At most three NPC tool calls per turn')
    actors = [a.get('actor') for a in agents]
    if any(not isinstance(n, str) for n in actors) or len(set(actors)) != len(actors) or any(n not in NPCS for n in actors): reject('Each NPC acts at most once per turn')
    action_shape(player, 'player')
    state = deepcopy(old); messages = [apply_tool(state, player)]
    for action in agents:
        messages.append(apply_tool(state, action))
        memory = f"第{old['turn'] + 1}回合：{action['action']}；玩家选择={state['decision'] or '未决定'}"
        state['memories'][action['actor']].append(memory)
    state['turn'] += 1
    if state['turn'] == LIMIT or player['action'] == 'finish':
        state['ending'] = ('stable_plan' if state['decision'] == 'stay' else
                           'collaborative_jump' if state['decision'] == 'accept' and state['relationships']['mira'] else
                           'solo_jump' if state['decision'] == 'accept' else 'undecided')
    return state, messages


def model_tool_options(old, player):
    """Expose legal proposals after the player's move without granting state writes."""
    state=deepcopy(old);apply_tool(state,player);options=[]
    for actor in NPCS:
        place=state['characters'][actor]
        options.append({'actor':actor,'action':'wait'})
        options.extend({'actor':actor,'action':'move','destination':p} for p in EDGES[place])
        for target,position in state['characters'].items():
            if target!=actor and position==place:
                options.append({'actor':actor,'action':'talk','target':target})
        for item,holder in state['items'].items():
            if holder=='location:'+place:
                options.append({'actor':actor,'action':'take','item':item})
            elif holder==actor:
                options.extend({'actor':actor,'action':'give','item':item,'target':target} for target,position in state['characters'].items() if target!=actor and position==place)
    return options


def local_agents(old, player):
    """Inspectable goal-seeking rules, explicitly not a real LLM invocation."""
    state = deepcopy(old); apply_tool(state, player); actions = []
    for npc in NPCS:
        here, player_place = state['characters'][npc], state['characters']['player']
        if here == player_place:
            action = {'actor': npc, 'action': 'talk', 'target': 'player', 'text': {
                'mira': ('既然你愿意尝试，我们先把合作边界写下来。' if state['decision'] == 'accept' else '留下也能开始新项目，我们仍然可以合作。' if state['decision'] == 'stay' else '新工作值得试，但先说清我们如何共同承担风险。'),
                'chen': ('你的选择已收到。下一步要安排交接，而不是只靠想象。' if state['decision'] else '新岗位有自由，也有资源不足的风险。你想先了解哪一边？'),
                'lin': ('笔记收到，我会接着把旧项目交接好。' if state['items']['notebook'] == 'lin' else '你带着项目笔记来了，能和我说说交接安排吗？' if state['items']['notebook'] == 'player' else '无论去哪，我们都可以把旧项目交接清楚。')}[npc]}
        else:
            destination = player_place if player_place in EDGES[here] else 'cafe'
            action = {'actor': npc, 'action': 'move', 'destination': destination}
        apply_tool(state, action); actions.append(action)
    return actions


def validate_game(old, proposed, event):
    check_shape(proposed)
    if old is None:
        if proposed != initial_state(proposed['scenario'], proposed['engine']): reject('Invalid initial world')
        return
    if event.get('type') != 'game.turn' or not isinstance(event.get('payload'), dict): reject('Only validated turns may change the world')
    payload = event['payload']
    if set(payload) != {'player', 'agents', 'request_key', 'expected_revision', 'mode', 'proof'}: reject('Invalid turn payload')
    if not isinstance(payload.get('proof'), str) or not hmac.compare_digest(sign_payload(payload, event.get('_context')), payload['proof']): reject('Use the authenticated game action endpoint')
    if event.get('expected_revision') != payload['expected_revision'] or event.get('idempotency_key') != payload['request_key']: reject('Turn provenance does not match its request')
    if payload['mode'] not in ('local', 'mock', 'real') or not isinstance(payload['request_key'], str) or type(payload['expected_revision']) is not int:
        reject('Invalid provenance')
    if old['engine'] == 'local' and (payload['mode'] != 'local' or payload['agents'] != local_agents(old, payload['player'])):
        reject('Local turns must preserve rule-agent provenance')
    if old['engine'] == 'model' and payload['mode'] not in ('mock', 'real'): reject('Model provenance required')
    expected, _ = transition(old, payload['player'], payload['agents'])
    if expected != proposed: reject('Proposed state does not follow from the recorded tools')


def register_game_rules(registry):
    registry.register('game', validate_game)


def ending_view(branch):
    state = branch['state']
    if not state['ending']: return None
    titles = {'stable_plan': '留下，不等于停在原地', 'collaborative_jump': '和搭档一起打开新门', 'solo_jump': '独自承担新的可能', 'undecided': '尚未做出的选择'}
    causes = [{'event_id': e['id'], 'sequence': e['sequence'], 'action': e['payload']['player']['action']} for e in branch['events'] if e['type'] == 'game.turn' and (e['payload']['player']['action'] in ('decide', 'finish') or (state['ending'] == 'collaborative_jump' and e['payload']['player']['action'] == 'talk' and e['payload']['player'].get('target') == 'mira'))]
    return {'code': state['ending'], 'title': titles[state['ending']], 'causes': causes,
            'explanation': '这是虚构世界规则产生的结局，不是现实概率。选择决定是否接受邀请；与搭档交谈影响合作结局。因果入口对应本分支实际事件。'}
