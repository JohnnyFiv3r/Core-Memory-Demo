from fastapi import APIRouter

router = APIRouter(prefix='/api', tags=['demo'])


@router.get('/meta')
def meta():
    return {
        'ok': True,
        'message': 'T1 scaffold active',
        'contract_status': 'stubs_only',
    }


# T2/T3 contract stubs — to be implemented against Core-Memory dependency
@router.get('/demo/state')
def demo_state():
    return {'ok': False, 'error': 'not_implemented'}


@router.post('/chat')
def chat():
    return {'ok': False, 'error': 'not_implemented'}


@router.post('/flush')
def flush():
    return {'ok': False, 'error': 'not_implemented'}


@router.post('/seed')
def seed():
    return {'ok': False, 'error': 'not_implemented'}


@router.post('/benchmark-run')
def benchmark_run():
    return {'ok': False, 'error': 'not_implemented'}
