import numpy as np
import math

DEBUG=True
def print_debug(message: str):
    if(DEBUG):
        print(message)

class BRAMAC():
    def __init__(self, precision:int, double_pumped: bool):
        self.prec = precision
        self.p = 40 #p = number of parallel mac2 operations
        self.maxdp = 2048 #max dot-product size before needing to read out accumulator
        self.mac2_startup =  2
        self.mac2_del = 5
        self.BRAM_rows = 128
        if precision==2:
            self.p = 80
            self.maxdp = 16
            #can only perform up to 8 MAC2's before needing to store accumulator
            #somewhere else
            self.mac2_del = 5 #num cc's to perform mac2
        elif precision==4:
            self.p = 40
            self.maxdp = 256
            self.mac2_del = 7
        elif precision==8:
            self.p = 20
            self.maxdp = 2048
            self.mac2_del = 11
        else:
            raise Exception("error, unsupported precision")
        
        self.rd_acc_delay = 8 #delay to read accumulator

        if double_pumped:
            self.p /= 2
            self.rd_acc_delay = 4
            self.mac2_del /= 2
        self.cc = 0
        self.lastop = 'none'
    
    def mac2(self):
        cc = 0
        if self.lastop != 'mac2':
            cc += self.mac2_startup
            self.lastop = 'mac2'
        cc += self.mac2_del
        return cc

    def readacc(self):
        cc = self.rd_acc_delay
        self.lastop = 'read'
        return cc

#Note: Because BRAMAC's weight rows are accumulated, they map more directly to "columns" in gemv operations

class PIM_FPGA():
    def __init__(self, precision, double_pumped):
        self.bram = BRAMAC(precision=precision, double_pumped=double_pumped)
        self.num_bram = 2423
        return
    
    def interAcc(self): #count cycles to accumulate between 
        cc = self.bram.readacc()
        cc += self.bram.mac2()
        return cc

    def partialAccRead(self): #count cycles required to read (& store) accumulator values
        #must read accumulator out after a certain number of MAC2s to prevent overflow
        cc = self.bram.readacc()
        cc += self.bram.mac2_startup #overhead of starting MAC2 again after performing a read
        return cc

    #numBRAM_split = number of brams that the columns are split across (increase parallelism at the cost of having to read-out and accumulate across BRAMs later)
    def dotpmv(self, inrow, incol, in2row, numBRAM_split):
        assert incol==in2row
        numBRAM_for_rows = math.ceil(inrow / self.bram.p)
        numBRAMs_for_cols = numBRAM_split
        numBRAMs_required = numBRAM_for_rows*numBRAMs_for_cols
        if(numBRAMs_required > self.num_bram): #perform recursive call breaking apart dot product
            print_debug("splitting up dotpmv operation")
            #split up by rows as those are relatively independent
            rows_at_a_time = math.floor(self.num_bram / numBRAMs_for_cols)
            full_dotp_runs = math.floor(inrow / rows_at_a_time) #cover all the "FULL" dot products. 
            full_run_cc = self.dotpmv(rows_at_a_time, incol, in2row, numBRAM_split)
            total_full_run_cc = full_run_cc * full_dotp_runs 
            #cover the left-over "partial" dot product
            left_over_rows = inrow % rows_at_a_time
            left_over_run_cc = self.dotpmv(left_over_rows, incol, in2row, numBRAM_split)
            return (total_full_run_cc + left_over_run_cc)
        else: #perform dot product
            vec_elements_at_a_time = 2*numBRAM_split
            num_intra_bram_mac2s = math.ceil(incol / vec_elements_at_a_time)
            #perform regular MAC2s
            intra_mac2_init_cc = self.bram.mac2() #done to account for pipelining start-up overhead
            intra_mac2_sub_seq_cc = self.bram.mac2() #subsequent pipelined mac2 delay
            total_intra_mac2_cc = intra_mac2_init_cc + ((num_intra_bram_mac2s-1) * intra_mac2_sub_seq_cc)
            #determine number of accumulator read_outs. Assume they are auto-accumulated by DSPs with no extra latency (other than read-out)
            #since it performs mac2, they perform dot-product 2 columns at a time
            num_max_dp_overflow = math.floor((num_intra_bram_mac2s * 2) / self.bram.maxdp) #use floor because the last acc value does not need to be read to prevent overflow 
            acc_read_cc = self.partialAccRead()
            total_acc_readout_cc = acc_read_cc * num_max_dp_overflow
            
            #perform inter-BRAM accumulation
            inter_acc = math.ceil(math.log2(numBRAM_split))
            inter_acc_cc = self.interAcc()
            total_inter_acc_cc = inter_acc_cc * inter_acc

            total_cc = total_intra_mac2_cc + total_acc_readout_cc + total_inter_acc_cc
            return total_cc


    def dotpmv_explore(self, inrow, incol, in2row):
        assert incol == in2row
        numBRAM_split = 1 #number of BRAMs that columns (dimension that is accumulated) are split between
        delays = []
        while (numBRAM_split*2) < incol:
            delay = self.dotpmv(inrow, incol, in2row, numBRAM_split)
            delays.append(delay)
            numBRAM_split += 1
        print_debug(str(len(delays)))
        return min(delays)


if __name__ == '__main__':
    fpga = PIM_FPGA(8, False)
    print(fpga.dotpmv_explore(400, 160, 160))
    #Double-pumped 8-bit vs radix-4 8-bit
    #0.145 vs 0.192