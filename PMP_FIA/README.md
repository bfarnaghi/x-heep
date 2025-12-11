# Compile and execute 

A. Generate a microcontroller:
https://x-heep.readthedocs.io/en/latest/GettingStarted/GeneratingMCU.html
```make mcu-gen CPU=cv32e20```

B. Simulate using Verilator:
https://x-heep.readthedocs.io/en/latest/How_to/Simulate.html
```make verilator-sim```
Results are visible within the folder ```x-heep/build/```

C. Compile the app
https://x-heep.readthedocs.io/en/latest/How_to/CompileApps.html
```make app PROJECT=<x-heep/sw/applications/APP_NAME>```

D. Run app
```cd ./build/openhwgroup.org_systems_core-v-mini-mcu_0/sim-verilator```
```./Vtestharness +firmware=../../../sw/build/main.hex```
Results are visible in the UART screen specified during execution

----------------------------------------------------------------------------

# X-HEEP (cv32e20, cv32e40s) RTL analysis under Skip Instruction Attack and its mitigations.

### To run experiments using different proposed mitigations:

0. If you want a new linker configuration change the ```x-heep/configs/general.hjson``` and follow points A, B and C.
  The linker file ```.ld``` then must be modified accordingly to the ```.hjson``` specifications

1. Choose which linker to use (NOTE!!: the linker in use is ONLY the one renamed ```link.ld```)
- PLAIN, PEA, DIs, TIS and MRC mitigations use the ```x-heep/sw/linker/link.ld```
- IMC mitigation uses the ```x-heep/sw/linker/link_IMC.ld```

2.A. In order to run different scenarios autonomously, in ```x-heep/run_pmp_scenarios.sh``` change: 
- the chosen CORE unser analysis: ```SIM_DIR="build/cv32e40s/sim-verilator"```
- the scenarios to test: ```declare -A SCENARIOS=(...)```

2.B. In order to run just one scenario each time, in ```x-heep/Makefile``` put the ```COMPILER_FLAGS ?= ``` equals to `-D<Scenario_Name>`

3. Run ```PMP_FIA/run_pmp_scenarios.sh```

4. Run ```PMP_FIA/analyze_pmp_metrics_xheep.py``` to gather information about the stats of the mitigations:
- ```python x-heep/analyze_pmp_metrics_xheep.py pmp_FIA_results_<date> PLAIN```