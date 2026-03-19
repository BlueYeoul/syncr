# syncr

Local → Server file sync tool for ML development.  
파일 저장하면 자동으로 서버에 올라갑니다.

## Install

```bash
pip install syncr
# or
uv add syncr
```

## Quick Start

```bash
# 1. 서버 등록
syncr server add myserver

# 2. 프로젝트 초기화 (프로젝트 폴더에서)
cd ~/my_project
syncr init

# 3. 첫 전체 sync
syncr push

# 4. 자동 watch 시작
syncr watch
```

## Commands

| Command | Description |
|---|---|
| `syncr server add <name>` | 서버 프로필 추가 |
| `syncr server list` | 등록된 서버 목록 |
| `syncr server remove <name>` | 서버 프로필 삭제 |
| `syncr server test <name>` | 연결 테스트 |
| `syncr init` | 현재 폴더를 syncr 프로젝트로 초기화 |
| `syncr push` | 전체 파일 서버로 push |
| `syncr push --dry-run` | 어떤 파일이 sync 될지 미리 확인 |
| `syncr watch` | 파일 변경 감지 → 자동 sync |
| `syncr status` | 현재 설정 확인 |

## .syncrignore

프로젝트 루트에 `.syncrignore` 파일로 제외할 파일/폴더 지정:

```
# 데이터, 체크포인트는 제외
data/
checkpoints/
*.pt
*.pth

# 로그
runs/
*.log
```

## Multiple Servers

```bash
syncr server add gpu-server-1
syncr server add gpu-server-2

# 특정 서버로 push
syncr push --server gpu-server-2
syncr watch --server gpu-server-2
```

## Auth Methods

**SSH Key (recommended):**
```
Auth method: key
SSH key path: ~/.ssh/id_rsa
```

**Password:**
```
Auth method: password
```
Password는 매번 입력하거나 config에 저장 가능 (비추천).

## Config Files

- `~/.syncr/config.toml` — 전역 서버 프로필
- `.syncr.toml` — 프로젝트별 설정 (git에 포함해도 OK)
- `.syncrignore` — 제외 패턴 (git에 포함 권장)
