# 1) 进入项目根目录
cd /Users/shichangwei/Desktop/goal/DeepTutor-1.0.0-beta.2

# 2) 激活虚拟环境（如未激活）
source .venv/bin/activate

# 3) 启动后端（终端A）
python3 -m deeptutor.api.run_server

# 4) 启动前端（终端B）
cd web
npm run dev
