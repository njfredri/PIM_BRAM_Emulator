import os, argparse
from BRAM import *

def parse_input(input_file) -> list:
    operations = [] #list of dictionaries
    fin = open(input_file)
    for line in fin.readlines():
        words = line.strip().split()
        if len(line) < 5:
            continue
        if '#' in words[0]:
            continue
        args = [int(x) for x in words[1:]]
        operations.append({'op': words[0], 'args': args})
    return operations
        
def run_operations(bit_prec, operations):
    pim = PIM_FPGA(base_prec=bit_prec, inc_acc_prec=False)
    for op in operations:
        prev_count = pim.bram.cycle_count
        match op['op'].strip():
            case 'gemv':
                pim.GEMV(op['args'][0], op['args'][1], op['args'][2], pim.base_prec, pim.base_prec, pim.base_prec, pim.increment_acc)
            case 'gemv_b':
                pim.GEMV_batched(op['args'][0], op['args'][1], op['args'][2], op['args'][3], pim.base_prec, pim.base_prec, pim.base_prec, pim.increment_acc)
            case 'dotp:':
                pim.dotproduct(op['args'][0], op['args'][1], op['args'][2], pim.base_prec, pim.base_prec, pim.increment_acc)
            case 'dotpmm:':
                pim.dotproductmm(op['args'][0], op['args'][1], op['args'][2], op['args'][3], pim.base_prec, pim.base_prec, pim.increment_acc)
            case 'dotpmm_b':
                pim.dotproductmm_batched(op['args'][0], op['args'][1], op['args'][2], op['args'][3], op['args'][4], pim.base_prec, pim.base_prec, pim.increment_acc)
        print(op['op'], ' cycles: ', pim.bram.cycle_count - prev_count)
    print('pim cycles: ', pim.bram.cycle_count)


parser = argparse.ArgumentParser()
parser.add_argument("input", help="input file (txt format)")

if __name__ == "__main__":
    args = parser.parse_args()
    ops = parse_input(args.input)
    bit_precisions = [8]
    for precision in bit_precisions:
        print('Bit-precision: ', precision)
        run_operations(precision, ops)