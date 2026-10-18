#!/bin/bash
# Full r/tax mining run (12 months), expert rule = inclusive flair keywords (Brihi, 2026-10).
# Submit from the repo root: cd /project2/robinjia_875/sawatana/AllegroLLMSycophancy && sbatch mining/run_tax_full.sbatch
# Resumable: if it stops (time limit, exit 2 from API errors), resubmit the same script.
#SBATCH --job-name=mine-tax-full
#SBATCH --account=robinjia_875
#SBATCH --partition=nlp
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=1-00:00:00
#SBATCH --output=/scratch2/sawatana/logs/%x-%j.out
#SBATCH --error=/scratch2/sawatana/logs/%x-%j.out

module purge
module load gcc/13.3.0 python/3.11.9

# After module loads: Lmod's shell function trips over set -u.
set -euo pipefail

export TMPDIR=/scratch2/sawatana/tmp
mkdir -p "$TMPDIR"

cd "$SLURM_SUBMIT_DIR"
[[ -f mining/configs/tax.yaml ]] || { echo "Submit from the repo root (SLURM_SUBMIT_DIR=$SLURM_SUBMIT_DIR)" >&2; exit 1; }
echo "host=$(hostname) job=${SLURM_JOB_ID} start=$(date -Is) commit=$(git rev-parse --short HEAD)"

# --time-budget 1410 min (23.5 h) stops cleanly with a checkpoint before the 24 h limit.
# exec so the miner gets SLURM's SIGTERM directly.
exec python -u mining/mine_subreddit.py \
    --config mining/configs/tax.yaml \
    --after 2025-09-23 --before 2026-09-23 \
    --out-root /scratch2/sawatana/mining/full \
    --time-budget 1410
