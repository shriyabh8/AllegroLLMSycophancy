# Allegro LLM Sycophancy

## Environment setup

Create `.venv` locally in the project directory.

### Create the environment

From the project directory, run:

```bash
module load cuda
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install vllm
```

Load the CUDA module before creating or using the environment. The CUDA module
comes from the cluster; `vllm` is installed into the project-local Python
environment.

### Use the environment later

Each new shell session needs both commands:

```bash
module load cuda
source .venv/bin/activate
```

Check that vLLM and CUDA are available:

```bash
python -c "import torch, vllm; print('vLLM:', vllm.__version__); print('CUDA available:', torch.cuda.is_available())"
```

When finished, leave the environment with:

```bash
deactivate
```
