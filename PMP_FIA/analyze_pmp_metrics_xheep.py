#!/usr/bin/env python3
# filepath: /home/g.perlo/x-heep/PMP_FIA/analyze_pmp_metrics_xheep.py

import os
import sys
import re
import subprocess
from pathlib import Path
import json
import shutil

# Estimated CPI for CV32E40S (from literature: ~1.3-1.5 for embedded code)
ESTIMATED_CPI = 1.4

def extract_pmp_instruction_count(log_file):
    """Extract PMP setup instruction count from X-HEEP simulation log"""
    try:
        with open(log_file, 'r') as f:
            content = f.read()
            
            # Search for the pattern "ins: X" printed by pmp_setup
            match = re.search(r'ins:\s*(\d+)', content)
            if match:
                instret = int(match.group(1))
                print(f"DEBUG: Found PMP instructions: {instret}")
                return instret
            
            # Alternative pattern: "instructions: X"
            match = re.search(r'\[MACHINE MODE\].*?instructions:\s*(\d+)', content)
            if match:
                instret = int(match.group(1))
                print(f"DEBUG: Found PMP instructions (alt pattern): {instret}")
                return instret
                
    except (FileNotFoundError, IOError) as e:
        print(f"DEBUG: Could not read {log_file}: {e}")
        
    print(f"DEBUG: No PMP instruction count found in {log_file}")
    return None

def extract_total_instruction_count(log_file):
    """Extract total instruction count from simulation log (if available)"""
    try:
        with open(log_file, 'r') as f:
            for line in f:
                # Search for patterns like "Total instructions: X"
                match = re.search(r'Total\s+instructions:\s*(\d+)', line)
                if match:
                    return int(match.group(1))
                # Or "EXIT SUCCESS after X instructions"
                match = re.search(r'after\s+(\d+)\s+instructions', line)
                if match:
                    return int(match.group(1))
    except FileNotFoundError:
        pass
    return None

def find_binary(scenario_dir: Path, build_dir: str = 'build'):
    """Find compiled binary in X-HEEP build directory"""
    candidates = [
        scenario_dir / build_dir / 'main.elf',
        scenario_dir / 'sw' / 'build' / 'main.elf',
        scenario_dir / 'build' / 'main.elf',
        scenario_dir / build_dir / 'main.o',
        scenario_dir / 'sw' / 'build' / 'main.o',
    ]
    for p in candidates:
        if p.exists():
            return p
    return None

def resolve_size_cmd():
    """Find available size command"""
    candidates = [
        ['riscv32-unknown-elf-size', '-A'],
        ['riscv64-unknown-elf-size', '-A'],
        ['riscv64-linux-gnu-size', '-A'],
        ['riscv32-unknown-linux-gnu-size', '-A'],
        ['riscv-none-elf-size', '-A'],
        ['llvm-size', '-A'],
        ['size', '-A'],
    ]
    for cmd in candidates:
        exe = cmd[0]
        if shutil.which(exe):
            try:
                subprocess.run([exe, '--version'],
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL,
                               check=True)
                return cmd
            except Exception:
                continue
    return None

SIZE_CMD = resolve_size_cmd()

def get_elf_sections(elf_file):
    """Get code and data memory footprint from ELF/OBJ"""
    code_tags = ['.text', '.rodata', '.init', '.fini', '.xheep_user_code', 
                 'user_code', 'pmp_user_code', 'pmp_monitor_code']
    data_tags = ['.data', '.bss', '.sbss', '.sdata', '.xheep_user_data',
                 'user_data', 'user_stack', '.heap', '.stack', 
                 'pmp_user_data', 'pmp_monitor_data']

    # 1) Try with 'size' command
    if SIZE_CMD:
        try:
            result = subprocess.run(
                SIZE_CMD + [str(elf_file)],
                capture_output=True, text=True, check=True
            )
            code_size = 0
            data_size = 0
            total_size = 0

            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) < 2:
                    continue
                sec = parts[0]
                if sec.lower() in ('section', 'idx', 'name', 'total'):
                    continue
                try:
                    sz = int(parts[1], 0)
                except ValueError:
                    continue

                if any(tag == sec or tag in sec for tag in code_tags):
                    code_size += sz
                elif any(tag == sec or tag in sec for tag in data_tags):
                    data_size += sz
                total_size += sz

            if code_size or data_size or total_size:
                return code_size, data_size, total_size
        except Exception as e:
            print(f"Warning: size failed on {elf_file}: {e}")

    # 2) Fallback: readelf
    try:
        re_out = subprocess.run(
            ['readelf', '-S', '-W', str(elf_file)],
            capture_output=True, text=True, check=True
        )
        sec_re = re.compile(r'\[\s*\d+\]\s+(\S+)\s+\S+\s+[0-9a-fA-Fx]+\s+\S+\s+([0-9a-fA-F]+)\s')
        code_size = 0
        data_size = 0
        total_size = 0
        for line in re_out.stdout.splitlines():
            m = sec_re.search(line)
            if not m:
                continue
            sec = m.group(1)
            try:
                sz = int(m.group(2), 16)
            except ValueError:
                continue
            if any(tag == sec or tag in sec for tag in code_tags):
                code_size += sz
            elif any(tag == sec or tag in sec for tag in data_tags):
                data_size += sz
            total_size += sz
        return code_size, data_size, total_size
    except Exception as e:
        print(f"Warning: Could not analyze binary {elf_file}: {e}")
        return None, None, None

def analyze_scenario(scenario_dir, log_pattern='uart_output.log', build_dir=''):
    """Analyze metrics for a single X-HEEP scenario"""
    metrics = {
        'scenario': Path(scenario_dir).name,
        'pmp_instructions': None,
        'pmp_estimated_cycles': None,
        'total_instructions': None,
        'code_size': None,
        'data_size': None,
        'total_size': None
    }

    scenario_path = Path(scenario_dir)
    
    # Search for log directly in the scenario directory
    log_files = []
    
    # If log_pattern is a relative path with wildcard
    if '*' in log_pattern:
        log_files = list(scenario_path.glob(log_pattern))
    else:
        # Specific log file (uart_output.log or simulation.log)
        log_file = scenario_path / log_pattern
        if log_file.exists():
            log_files = [log_file]
        # Fallback: search for uart0.log from testbench
        elif (scenario_path / 'uart0.log').exists():
            log_files = [scenario_path / 'uart0.log']
    
    # Also search in common subdirectories if not found
    if not log_files:
        for subdir in ['', 'build/cv32e40s/sim-verilator', 'sim', 'logs']:
            pattern_path = scenario_path / subdir / log_pattern if subdir else scenario_path / log_pattern
            if pattern_path.exists():
                log_files = [pattern_path]
                break
    
    if log_files:
        log_file = log_files[0]  # Use first match
        print(f"DEBUG: Using log file: {log_file}")
        
        metrics['pmp_instructions'] = extract_pmp_instruction_count(str(log_file))
        metrics['total_instructions'] = extract_total_instruction_count(str(log_file))
        
        # Estimate cycles using fixed CPI
        if metrics['pmp_instructions']:
            metrics['pmp_estimated_cycles'] = int(metrics['pmp_instructions'] * ESTIMATED_CPI)
            
        print(f"DEBUG: {metrics['scenario']} - PMP Instructions: {metrics['pmp_instructions']}, "
              f"Estimated Cycles: {metrics['pmp_estimated_cycles']}")
    else:
        print(f"Warning: No log files matching '{log_pattern}' found in {scenario_dir}")

    # Find binary - search in scenario directory or in build_dir if specified
    bin_paths = [
        scenario_path / 'main.elf',
        scenario_path / 'main.o',
    ]
    
    if build_dir:
        bin_paths.extend([
            scenario_path / build_dir / 'main.elf',
            scenario_path / build_dir / 'main.o',
        ])
    
    bin_path = None
    for p in bin_paths:
        if p.exists():
            bin_path = p
            break
    
    if bin_path:
        print(f"DEBUG: Found binary at: {bin_path}")
        c, d, t = get_elf_sections(str(bin_path))
        metrics['code_size'], metrics['data_size'], metrics['total_size'] = c, d, t
        print(f"DEBUG: Binary sizes - Code: {c}, Data: {d}, Total: {t}")
    else:
        print(f"Warning: No binary found in {scenario_dir}")

    return metrics

def calculate_overhead(baseline, target, metric_name):
    """Calculate percentage overhead"""
    if baseline is None or target is None or baseline == 0:
        return None
    return ((target - baseline) / baseline) * 100

def generate_report(results_dir, baseline_name='PLAIN', log_pattern='uart_output.log', build_dir=''):
    """Generate comparative report for all X-HEEP scenarios"""
    
    results_path = Path(results_dir)
    
    # If results_dir is directly a directory with scenarios
    scenario_dirs = [d for d in results_path.iterdir() if d.is_dir()]
    
    # If there are no subdirectories, use results_dir itself as single scenario
    if not scenario_dirs:
        scenario_dirs = [results_path]
    
    print(f"\n{'='*130}")
    print(f"X-HEEP PMP FIA Comparative Analysis")
    print(f"Results directory: {results_dir}")
    print(f"Estimated CPI: {ESTIMATED_CPI} (CV32E40S typical)")
    print(f"{'='*130}\n")
    
    # Analyze all scenarios
    all_metrics = []
    for scenario_dir in sorted(scenario_dirs):
        metrics = analyze_scenario(scenario_dir, log_pattern, build_dir)
        all_metrics.append(metrics)
    
    # Find baseline
    baseline = None
    for metrics in all_metrics:
        if metrics['scenario'] == baseline_name or baseline_name in metrics['scenario']:
            baseline = metrics
            break
    
    # Print main metrics table
    header = f"{'Scenario':<25} {'PMP Instr':<15} {'Est. Cycles':<15} {'Code (B)':<15} {'Data (B)':<15} {'Total (B)':<15}"
    print(header)
    print(f"{'-'*115}")
    
    for metrics in all_metrics:
        print(f"{metrics['scenario']:<25} "
              f"{str(metrics['pmp_instructions']) if metrics['pmp_instructions'] else 'N/A':<15} "
              f"{str(metrics['pmp_estimated_cycles']) if metrics['pmp_estimated_cycles'] else 'N/A':<15} "
              f"{str(metrics['code_size']) if metrics['code_size'] else 'N/A':<15} "
              f"{str(metrics['data_size']) if metrics['data_size'] else 'N/A':<15} "
              f"{str(metrics['total_size']) if metrics['total_size'] else 'N/A':<15}")
    
    # Print overhead comparison
    if baseline and baseline['pmp_instructions']:
        print(f"\n{'='*130}")
        print(f"Overhead compared to {baseline['scenario']}:")
        print(f"{'='*130}\n")
        
        header_oh = f"{'Scenario':<25} {'PMP Instr OH (%)':<20} {'Est. Cycles OH (%)':<20} {'Code OH (%)':<20}"
        print(header_oh)
        print(f"{'-'*115}")
        
        for metrics in all_metrics:
            if metrics['scenario'] != baseline['scenario'] and metrics['pmp_instructions']:
                pmp_instr_overhead = calculate_overhead(baseline['pmp_instructions'], 
                                                       metrics['pmp_instructions'], 'pmp_instructions')
                cycles_overhead = calculate_overhead(baseline['pmp_estimated_cycles'], 
                                                    metrics['pmp_estimated_cycles'], 'cycles')
                code_overhead = calculate_overhead(baseline['code_size'], metrics['code_size'], 'code_size')
                
                pmp_oh_str = f"{pmp_instr_overhead:+.2f}" if pmp_instr_overhead is not None else 'N/A'
                cyc_oh_str = f"{cycles_overhead:+.2f}" if cycles_overhead is not None else 'N/A'
                code_oh_str = f"{code_overhead:+.2f}" if code_overhead is not None else 'N/A'
                
                print(f"{metrics['scenario']:<25} {pmp_oh_str:<20} {cyc_oh_str:<20} {code_oh_str:<20}")
    
    # Save to CSV
    csv_file = results_path / 'metrics_comparison_xheep.csv'
    with open(csv_file, 'w') as f:
        f.write("Scenario,PMP_Instructions_Count,PMP_Estimated_Cycles_CPI_{:.1f},"
                "Code_Memory_Footprint_B,Data_Memory_Footprint_B,Total_Size_B\n".format(ESTIMATED_CPI))
        for metrics in all_metrics:
            f.write(f"{metrics['scenario']},"
                   f"{metrics['pmp_instructions'] or 0},"
                   f"{metrics['pmp_estimated_cycles'] or 0},"
                   f"{metrics['code_size'] or 0},"
                   f"{metrics['data_size'] or 0},"
                   f"{metrics['total_size'] or 0}\n")
    
    print(f"\n{'='*130}")
    print(f"Metrics saved to: {csv_file}")
    
    # Save overhead comparison
    if baseline and baseline['pmp_instructions']:
        overhead_csv = results_path / 'overhead_comparison_xheep.csv'
        with open(overhead_csv, 'w') as f:
            f.write(f"Scenario,PMP_Instructions_Overhead_%,Estimated_Cycles_Overhead_%,Code_Overhead_%\n")
            for metrics in all_metrics:
                if metrics['scenario'] != baseline['scenario'] and metrics['pmp_instructions']:
                    pmp_instr_oh = calculate_overhead(baseline['pmp_instructions'], 
                                                     metrics['pmp_instructions'], 'pi')
                    cycles_oh = calculate_overhead(baseline['pmp_estimated_cycles'], 
                                                  metrics['pmp_estimated_cycles'], 'cyc')
                    code_oh = calculate_overhead(baseline['code_size'], metrics['code_size'], 'cs')
                    
                    f.write(f"{metrics['scenario']},"
                           f"{pmp_instr_oh or 0:.2f},"
                           f"{cycles_oh or 0:.2f},"
                           f"{code_oh or 0:.2f}\n")
        
        print(f"Overhead comparison saved to: {overhead_csv}")
    
    # Summary
    print(f"\n{'='*130}")
    print("Summary:")
    print(f"{'='*130}")
    print(f"Total scenarios analyzed: {len(all_metrics)}")
    print(f"Baseline scenario: {baseline['scenario'] if baseline else 'Not found'}")
    if baseline:
        print(f"Baseline PMP instructions: {baseline['pmp_instructions']}")
        print(f"Baseline estimated cycles (CPI={ESTIMATED_CPI}): {baseline['pmp_estimated_cycles']}")
        print(f"Baseline code size: {baseline['code_size']} bytes")
    
    print(f"\nNote: Cycle counts are estimated using CPI={ESTIMATED_CPI} since mcycle counter")
    print(f"      is not functional in CV32E40S. Actual cycles may vary ±10-20%.")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <results_directory> [baseline_scenario_name] [log_pattern] [build_dir]")
        print(f"\nExamples:")
        print(f"  {sys.argv[0]} pmp_fia_results_20251112_143020 PLAIN")
        print(f"  {sys.argv[0]} pmp_fia_results_20251112_143020 PLAIN uart_output.log")
        print(f"  {sys.argv[0]} . PLAIN uart0.log sw/build")
        print(f"\nDefault values:")
        print(f"  baseline_scenario_name: PLAIN")
        print(f"  log_pattern: uart_output.log (UART output from program)")
        print(f"  build_dir: '' (search in scenario directory)")
        print(f"\nNote: The script looks for UART output (uart_output.log or uart0.log)")
        print(f"      which contains the actual program output with 'ins: X' metrics.")
        sys.exit(1)
    
    results_dir = sys.argv[1]
    baseline_name = sys.argv[2] if len(sys.argv) > 2 else 'PLAIN'
    log_pattern = sys.argv[3] if len(sys.argv) > 3 else 'uart_output.log'
    build_dir = sys.argv[4] if len(sys.argv) > 4 else ''
    
    if not Path(results_dir).exists():
        print(f"Error: Directory {results_dir} not found")
        sys.exit(1)
    
    print(f"DEBUG: Configuration:")
    print(f"  Results dir: {results_dir}")
    print(f"  Baseline: {baseline_name}")
    print(f"  Log pattern: {log_pattern}")
    print(f"  Build dir: {build_dir if build_dir else '(scenario root)'}")
    print(f"  Estimated CPI: {ESTIMATED_CPI}")
    
    generate_report(results_dir, baseline_name, log_pattern, build_dir)
