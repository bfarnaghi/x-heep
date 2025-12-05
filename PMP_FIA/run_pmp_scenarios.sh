#!/bin/bash
# Script to automatically run all PMP scenarios and save results

SIMULATION_TIMEOUT=180 # seconds

set -e  # Exit on error

# Detect if we are in PMP_FIA/ or in x-heep/
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "$SCRIPT_DIR" == */PMP_FIA ]]; then
    # We are in x-heep/PMP_FIA, go up one directory
    XHEEP_ROOT="$(dirname "$SCRIPT_DIR")"
else
    # We are directly in x-heep/
    XHEEP_ROOT="$SCRIPT_DIR"
fi

echo "X-HEEP root: $XHEEP_ROOT"
cd "$XHEEP_ROOT"

# Results directory (relative to script)
RESULTS_DIR="$SCRIPT_DIR/outputs/pmp_fia_results_$(date +%Y%m%d_%H%M%S)"
PROJECT="pmp_driver"
SIM_DIR="$XHEEP_ROOT/build/cv32e40s/sim-verilator"

# Scenarios to test (compiler flags)
declare -A SCENARIOS=(
    ["PLAIN"]="-DPLAIN"
    #["PEA"]="-DPEA"
    #["MRC"]="-DMRC"
    #["DIs"]="-DDIs"
    #["TIs"]="-DTIs"
    #["IMC"]="-DIMC"
)

echo "=================================="
echo "X-HEEP PMP FIA Test Suite"
echo "=================================="
echo "Results directory: $RESULTS_DIR"
echo "Project: $PROJECT"
echo ""

# Create results directory
mkdir -p "$RESULTS_DIR"

# Backup original Makefile
MAKEFILE="$XHEEP_ROOT/Makefile"
if [ ! -f "$MAKEFILE.backup_pmp" ]; then
    cp "$MAKEFILE" "$MAKEFILE.backup_pmp"
    echo "Makefile backed up to Makefile.backup_pmp"
fi

# Save configuration
cat > "$RESULTS_DIR/test_config.txt" <<EOF
Test run: $(date)
Project: $PROJECT
Scenarios: ${!SCENARIOS[@]}
X-HEEP path: $XHEEP_ROOT
Script path: $SCRIPT_DIR
EOF

# Function to run a single scenario
run_scenario() {
    local scenario_name=$1
    local cflags=$2
    
    echo ""
    echo "=========================================="
    echo "Running scenario: $scenario_name"
    echo "COMPILER_FLAGS: $cflags"
    echo "=========================================="
    
    # Directory for this scenario
    local scenario_dir="$RESULTS_DIR/$scenario_name"
    mkdir -p "$scenario_dir"
    
    echo "Step 1: Updating Makefile COMPILER_FLAGS to: $cflags"
    sed -i "s/^COMPILER_FLAGS ?= .*/COMPILER_FLAGS ?= $cflags/" "$MAKEFILE"
    
    echo "Step 2: Cleaning previous build..."
    make -C "$XHEEP_ROOT" clean > "$scenario_dir/build.log" 2>&1 || true
    
    echo "Step 3: Compiling $scenario_name..."
    if make -C "$XHEEP_ROOT" app PROJECT=$PROJECT >> "$scenario_dir/build.log" 2>&1; then
        echo "  ✓ Compilation successful"
        
        # Copy compiled binary
        if [ -f "$XHEEP_ROOT/sw/build/main.elf" ]; then
            cp "$XHEEP_ROOT/sw/build/main.elf" "$scenario_dir/main.elf"
            echo "  ✓ Binary saved"
        fi
        
        echo "Step 4: Running simulation..."
        cd "$SIM_DIR"
        
        if timeout $SIMULATION_TIMEOUT ./Vtestharness +firmware=../../../sw/build/main.hex > /dev/null 2>&1; then
            echo "  ✓ Simulation completed"
        else
            EXIT_CODE=$?
            if [ $EXIT_CODE -eq 124 ]; then
                echo "  ⚠ Simulation timeout ($SIMULATION_TIMEOUT s)"
            else
                echo "  ✗ Simulation failed (exit code: $EXIT_CODE)"
            fi
        fi
        
        echo "Step 5: Extracting metrics from uart0.log..."
        if [ -f "uart0.log" ]; then
            ins=$(grep -oP 'ins:\s*\K\d+' uart0.log 2>/dev/null || echo "N/A")
            echo "$scenario_name: $ins instructions" | tee -a "$scenario_dir/metrics.txt"
            cp uart0.log "$scenario_dir/uart_output.log"
            echo "  ✓ Metrics extracted"
        else
            echo "  ⚠ No uart0.log found"
        fi
        
        cd "$XHEEP_ROOT"
        
    else
        echo "  ✗ Compilation failed"
    fi
    
    echo "Scenario $scenario_name completed"
}

# Run all scenarios
for scenario in "${!SCENARIOS[@]}"; do
    run_scenario "$scenario" "${SCENARIOS[$scenario]}"
done

# Restore original Makefile
if [ -f "$MAKEFILE.backup_pmp" ]; then
    mv "$MAKEFILE.backup_pmp" "$MAKEFILE"
    echo ""
    echo "Makefile restored to original state"
fi

echo ""
echo "=========================================="
echo "All scenarios completed!"
echo "=========================================="
echo "Results saved in: $RESULTS_DIR"
echo ""
echo "To analyze results, run:"
echo "  python3 $SCRIPT_DIR/analyze_pmp_metrics_xheep.py $RESULTS_DIR PLAIN uart_output.log"
echo ""

# Show results preview
echo "Quick preview:"
echo "----------------------------------------"
for scenario in "${!SCENARIOS[@]}"; do
    log_file="$RESULTS_DIR/$scenario/uart_output.log"
    if [ -f "$log_file" ]; then
        ins=$(grep -oP 'ins:\s*\K\d+' "$log_file" 2>/dev/null || echo "N/A")
        echo "$scenario: $ins instructions"
    fi
done
echo "----------------------------------------"

chmod +x "$0"