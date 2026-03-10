import numpy as np
import math

DEBUG=True
def print_debug(message: str):
    if(DEBUG):
        print(message)

###This class is intended to emulate just the BRAM. It will emulate the memory array and bit-serial periphery
###For now, it will do cycle counts, not necessarily logic (yet)
class BRAM():
    def __init__(self, num_col=160, num_row=128, col_muxing=4, radix4=False):
        self.PIM_mode = False
        self.num_ports = 2
        # self.mem_array = np.zeros(shape=(num_col, num_row), dtype=np.bool)
        self.bit_width = num_col/col_muxing
        self.num_pes = num_col/col_muxing
        self.maxBRAMJumps = 9
        self.base_word_size = col_muxing #4

        # # self.reg_file = np.zeros(shape=(self.bit_width*2)) #regular register file
        # self.pipe_reg2 = np.zeros(shape=((self.bit_width*2)+1)) #register after networking
        # self.pipe_reg2 = np.zeros(shape=((self.bit_width*2))) #register after opmux
        # self.pipe_reg3 = np.zeros(shape=(self.bit_width)) #write-back register

        self.cycle_count = 0
        self.mult_cycles = 0
        self.networking_2 = True
        self.radix4 = radix4
        self.manual_cc = 0 #cycle count done manually

    def three_cycle_op(self): #for addition, subtraction, and copy (just booth's)
        #read cycle
        self.cycle_count +=1
        #execute
        self.cycle_count +=1
        #writeback
        self.cycle_count +=1
        return 3
    
    def two_cycle_op_iter(self):
        #execute
        self.cycle_count +=1
        #writeback/read
        self.cycle_count +=1
        return 2

    def two_cycle_op_first_iter(self):
        #read
        self.cycle_count +=1
        #execute
        self.cycle_count +=1
        #writeback/read
        self.cycle_count +=1
        return 3

    def addsub2op(self, bit_length:int, rownum1:int , rownum2:int, rowdes:int):
        bitcnt = 0
        cc = 0
        while bitcnt < bit_length:
            cc += self.three_cycle_op()
            bitcnt += 4
        return cc
        
    
    def add1op(self, bit_length:int):
        bitcnt = self.base_word_size
        cc = 0
        cc += self.two_cycle_op_first_iter()
        while bitcnt < bit_length:
            cc += self.two_cycle_op_iter()
            bitcnt += self.base_word_size
        return cc

    def mult(self, bit_length:int, mult_length:int):
        mult_acc_add_length = bit_length + 1 #This is to handle overlap when accumulator's current bits are split across rows. Faster than doing "acc_length" operations every time
        #executing extra 4-bits also allows the radix 4 add/sub 2x to work (need to handle cases with an extra bit offset)
        mult_iterations = mult_length
        print('bit_length ' , mult_acc_add_length)
        cc = 0
        if self.radix4:
            mult_iterations = math.ceil(mult_length/2)
        for i in range(mult_iterations):
            #Spend 1 CC to read the multiplier bits
            oldcount = self.cycle_count
            self.cycle_count += 1
            cc += 1
            #Perform the 2-op add/sub/cpy between the accumulator and multiplicand
            cc += self.addsub2op(bit_length=mult_acc_add_length, rownum1=0, rownum2=0, rowdes=0)
            self.mult_cycles += self.cycle_count - oldcount
        return cc
    
    def offloadToDSPs(self, bit_length:int): #not used
        #immediately read from data port B using the output shift-reg
        self.cycle_count += 1 #perform the bit-parallel operation using the DSP
        #start writing back in bit-serial form
        self.cycle_count += bit_length
        

class PIM_FPGA():
    def __init__(self, base_prec=4, inc_acc_prec=False, radix4=False):
        self.num_bram = 2423
        self.bram = BRAM(radix4=radix4)
        self.pes_per_bram = self.bram.num_pes
        self.base_prec = base_prec
        self.increment_acc = inc_acc_prec

    def intraAcc(self, num_words, bit_precision, inc_acc_prec=False):
        acc_prec = bit_precision #account for increasing precision req for acc
        num_iter = math.ceil(math.log2(num_words))
        cc=0
        for i in range(num_iter):
            if(inc_acc_prec): 
                acc_prec += 1
            cc += self.bram.add1op(acc_prec)
        if(inc_acc_prec): 
                acc_prec -= 1
        return acc_prec, cc
    
    def travel_data(self, bit_length:int, distance:int): #move data close enough to be operated on in an inter-BRAM operation
        dis = distance
        cc = 0
        while dis > 9:
            # print("must copy data")
            if self.bram.networking_2==True:
                self.bram.cycle_count += math.ceil(bit_length/4)
                cc += math.ceil(bit_length/4)
            else:
                cc += self.bram.add1op(bit_length) #perform a copy across 9 BRAMs
            # print_debug("performing copy")
            dis -= 9
        return cc
    
    def interAcc(self, num_BRAMS:int, bit_precision:int, inc_acc_prec=False):
        words = num_BRAMS
        distance = 1
        to_travel = 1
        acc_precision = bit_precision
        cc = 0
        while words > 1:
            if(inc_acc_prec):
                acc_precision += 1
            cc += self.travel_data(acc_precision, to_travel) #move data close enough to perform the 1-op addition
            cc += self.bram.add1op(acc_precision)
            words = math.ceil(words/2)
            to_travel *= min(2,math.ceil(num_BRAMS/2))

        return acc_precision, cc

    def GEMV(self, mrow, mcol, vsize, mprec, vprec, bias_prec, inc_acc_prec=False):
        # print(mcol, vsize)
        assert mcol==vsize
        
        #if the GEMV operation is too large, break it up into peices
        num_req_BRAM_for_rows = mrow
        num_req_BRAM_for_acc  = math.ceil(mcol / self.pes_per_bram)
        if num_req_BRAM_for_acc > self.num_bram:
            print("error, need ", num_req_BRAM_for_acc, "BRAMs for just accumulation")
            exit(1)

        num_req_BRAM = num_req_BRAM_for_rows * num_req_BRAM_for_acc
        num_runs = 1 #number of smaller GEMV operations to perform the current operation
        if num_req_BRAM > self.num_bram:
            rows_per_run = math.floor(self.num_bram / num_req_BRAM_for_acc)
            num_runs = math.ceil(mrow / rows_per_run)
            #perform all those smaller GEMV runs
            for i in range(num_runs):
                self.GEMV(rows_per_run, mcol, vsize, mprec, vprec, bias_prec, inc_acc_prec=inc_acc_prec)
        else: #otherwise, just perform GEMV operation as usual
            #perform element-wise multiplication
            self.bram.mult(vprec, mprec)
            #perform intra-BRAM accumulation
            product_prec = (vprec+mprec)
            acc_precision = product_prec + math.ceil(math.log2(mcol)) + 1
            if(inc_acc_prec==True):
                acc_precision = product_prec #start low. Increase as you go

            # print("og acc precision ", acc_precision)

            num_words = mcol
            if num_words >= 40:
                acc_ret, __ = self.intraAcc(40, acc_precision, inc_acc_prec=inc_acc_prec)
                if(inc_acc_prec==True):
                    acc_precision = acc_ret #start low. Increase as you go
            else:
                acc_ret, __  = self.intraAcc(num_words, acc_precision, inc_acc_prec=inc_acc_prec)
                if(inc_acc_prec==True):
                    acc_precision = acc_ret #start low. Increase as you go
            num_words = math.ceil(num_words/40)
            #perform inter-BRAM accumulation (if needed)
            if num_words > 1:
                acc_ret, __= self.interAcc(num_words, acc_precision,  inc_acc_prec=inc_acc_prec)
                num_words = 1
                if(inc_acc_prec==True):
                    acc_precision = acc_ret #start low. Increase as you go

            #perform addition (add the bias)
            self.bram.addsub2op(bias_prec, 0,0,0)
            # print("final acc precision ", acc_precision)
    
    def GEMV_batched(self, mrow, mcol, vsize, num_patches, mprec, vprec, bias_prec, inc_acc_prec=False):
        # num_req_BRAM_for_rows = mrow
        # num_req_BRAM_for_acc  = math.ceil(mcol / self.pes_per_bram)
        # print(num_req_BRAM_for_acc*num_req_BRAM_for_rows)
        for patch in range(num_patches):
            self.GEMV(mrow, mcol, vsize, mprec, vprec, bias_prec, inc_acc_prec=inc_acc_prec)

    def dotproduct(self, mrow, mcol, vsize, mprec, vprec, inc_acc_prec=False):
        if(mcol!=vsize):
            print(mcol, ' ', vsize)
        assert mcol==vsize
        #if the GEMV operation is too large, break it up into peices
        num_req_BRAM_for_rows = mrow
        num_req_BRAM_for_acc  = math.ceil(mcol / self.pes_per_bram)
        if num_req_BRAM_for_acc > self.num_bram:
            print("error, need ", num_req_BRAM_for_acc, "BRAMs for just accumulation")
            exit(1)

        num_req_BRAM = num_req_BRAM_for_rows * num_req_BRAM_for_acc
        num_runs = 1 #number of smaller GEMV operations to perform the current operation
        if num_req_BRAM > self.num_bram:
            rows_per_run = math.floor(self.num_bram / num_req_BRAM_for_acc)
            num_runs = math.ceil(mrow / rows_per_run)
            #perform all those smaller GEMV runs
            for i in range(num_runs):
                self.dotproduct(rows_per_run, mcol, vsize, mprec, vprec, inc_acc_prec=inc_acc_prec)
        else: #otherwise, just perform GEMV operation as usual
            #perform element-wise multiplication
            self.bram.mult(vprec, mprec)
            #perform intra-BRAM accumulation
            product_prec = (vprec+mprec)
            acc_precision = product_prec + math.ceil(math.log2(mcol)) + 1
            if(inc_acc_prec):
                acc_precision = product_prec #start low. Increase as you go

            num_words = mcol
            if num_words >= 40:
                acc_ret, __ = self.intraAcc(40, acc_precision, inc_acc_prec=inc_acc_prec)
                if(inc_acc_prec):
                    acc_precision = acc_ret #start low. Increase as you go
            else:
                acc_ret, __  = self.intraAcc(num_words, acc_precision, inc_acc_prec=inc_acc_prec)
                if(inc_acc_prec):
                    acc_precision = acc_ret #start low. Increase as you go

            num_words = math.ceil(num_words/40)
            #perform inter-BRAM accumulation (if needed)
            if num_words > 1:
                self.interAcc(num_words, acc_precision, inc_acc_prec=inc_acc_prec)
                num_words = 1

    


    def dotproductmm(self, mrow, mcol, m2row, m2col, mprec, m2prec, inc_acc_prec=False):
        try:
            assert mcol==m2row
            #base dotp operation = <mrow,mcol> * <m2row>. Do that dotp m2col-times
            base_dotp_num_bram = math.ceil(mcol/40)*mrow
            print('\tbase_dotp_num_bram', base_dotp_num_bram)
            dotps_at_a_time = max(math.floor(self.num_bram / base_dotp_num_bram),1)
            if dotps_at_a_time==0:
                dotps_at_a_time = self.num_bram / base_dotp_num_bram
            print('\tdotps_at_a_time ', dotps_at_a_time)
            dotp_iterations = math.ceil(m2col / dotps_at_a_time)
            print_debug('dotp iter: ' + str(dotp_iterations))
            for i in range(dotp_iterations): #perform all mv dotp operations
                # print(i)
                self.dotproduct(mrow, mcol, m2row, mprec, m2prec, inc_acc_prec=inc_acc_prec)
                #TODO: Add in same way to account for overhead of concatenating DP-MV result into DP-MM result
        except:
            base_dotp_num_bram = math.ceil(mcol/40)*mrow
            dotp_iterations = math.ceil(m2col / dotps_at_a_time)
            print('ERROR:', mcol, mrow, self.num_bram)

    def dotproductmm_batched(self, mrow, mcol, m2row, m2col, mprec, m2prec, num_batches, inc_acc_prec=False):
        # print(mcol, m2row)
        assert mcol==m2row
        #base dotp operation = <mrow,mcol> * <m2col>. Do that dotp m2row-times. 
        #Then perform the matrix-matrix dotp num_batches-times.
        base_dotp_num_bram = math.ceil(mcol/40)*mrow
        dotps_at_a_time = math.floor(self.num_bram / base_dotp_num_bram)
        if dotps_at_a_time==0:
                dotps_at_a_time = self.num_bram / base_dotp_num_bram
        dotp_iterations = math.ceil(m2col * num_batches / dotps_at_a_time)
        for i in range(dotp_iterations): #perform all mv dotp operations
            self.dotproduct(mrow, mcol, m2row, mprec, m2prec, inc_acc_prec=inc_acc_prec)
    
    def conv1(self, inh, inw, kh, kw, sh, sw, ph, pw, mprec, m2prec, bias_prec, inc_acc_prec=False):
        gemm_dim = Im2Col.conv_out_to_gemm(inh, inw, kh, kw, sh, sw, ph, pw)
        self.dotproductmm(gemm_dim[0], gemm_dim[1], gemm_dim[2], gemm_dim[3], mprec, m2prec, inc_acc_prec)
        print(self.bram.cycle_count)
        self.bram.addsub2op(bias_prec, 0,0,0) #add the bias
        return
#  0 = filter width
#  1 = filter height
#  2 = input  channel
#  3 = output height
#  4 = output width
#  5 = output channel
    #convolution when given just the output size, kernel size, and in channels
    def conv2(self, kh, kw, inc, outh, outw, outc, mprec, m2prec, bias_prec, inc_acc_prec=False):
        gemm_dim = Im2Col.conv_out_to_gemm(kh, kw, inc, outh, outw, outc)
        # self.dotproductmm(gemm_dim[0], gemm_dim[1], gemm_dim[2], gemm_dim[3], mprec, m2prec, inc_acc_prec)
        # print(self.bram.cycle_count)
        # self.bram.addsub2op(bias_prec, 0,0,0) #add the bias
        self.GEMV_batched(gemm_dim[0], gemm_dim[1], gemm_dim[2], gemm_dim[3], mprec, m2prec, bias_prec, inc_acc_prec)
        return
    
    def conv3(self, kh, kw, inc, outh, outw, outc, mprec, m2prec, bias_prec, inc_acc_prec=False):
        bram_width = math.ceil(outw/self.bram.num_pes)
        num_brams_full_img = outh * inc * bram_width 
        num_parts_per_filter = math.ceil(num_brams_full_img* outc / self.num_bram)
        print(bram_width, num_brams_full_img, num_parts_per_filter)

        for part in range(num_parts_per_filter):
            mults=kh*kw
            for mult in range(mults):
                self.bram.mult(mprec, m2prec)
            acc_prec = mprec+m2prec
            for i in range(kh): #accumulate the rows
                self.bram.addsub2op(acc_prec, 0, 0, 0)
                acc_prec += 1
            for i in range(kw): #accumulate the columns
                self.bram.addsub2op(acc_prec, 0, 0, 0)
                acc_prec += 1
            for i in range(inc): #accumulate along channels
                self.bram.addsub2op(acc_prec,0,0,0)
                acc_prec += 1
            #add the bias
            self.bram.addsub2op(bias_prec,0,0,0)

    def dotpmv(self, mrow, mcol, vsize, mprec, overlap:int, inc_acc_prec=False):
        #overlap= number of columns per bram (aka 40xoverlap columns)
        numBRAM_for_cols = math.ceil(mcol / (self.bram.num_pes * overlap))
        numBRAM_for_rows = mrow
        numBRAM_required = numBRAM_for_rows*numBRAM_for_cols
        if(numBRAM_required > self.num_bram): #perform recursive call breaking apart dot product
            print_debug("splitting up dotpmv operation")
            #split up by rows as those are relatively independent
            rows_at_a_time = math.floor(self.num_bram / numBRAM_for_cols)
            full_dotp_runs = math.floor(mrow / rows_at_a_time) #cover all the "FULL" dot products. 
            
            full_dotp_cc   = self.dotpmv(rows_at_a_time, mcol, vsize, mprec, overlap, inc_acc_prec)
            total_full_run_cc = full_dotp_cc*full_dotp_runs
            #cover the left-over "partial" dot product
            left_over_rows = mrow % rows_at_a_time
            left_over_run_cc = self.dotpmv(left_over_rows, mcol, vsize, mprec, overlap, inc_acc_prec)
            return (total_full_run_cc + left_over_run_cc)
        else: #perform dot product
            #perform regular MAC operations (overlap)
            num_macs = overlap
            print_debug('num macs: ' + str(num_macs))
            mult_cycles = self.bram.mult(self.base_prec, mprec)
            print_debug('mult cycles: ' + str(mult_cycles))
            total_mac_cycles = num_macs * mult_cycles
            print_debug('total mult cycles: ' + str(mult_cycles))
            
            acc_prec = mprec + self.base_prec + num_macs - 1
            
            #perform intra-BRAM accumulation
            acc_prec, intra_cc = self.intraAcc(min(self.bram.num_pes, mcol), acc_prec, inc_acc_prec=inc_acc_prec)
            
            #if needed, perform inter-BRAM accumulation
            inter_cc = 0
            if numBRAM_for_cols > 1:
                acc_prec, inter_cc = self.interAcc(numBRAM_for_cols, acc_prec, inc_acc_prec=inc_acc_prec)
                
            total_cc = total_mac_cycles + intra_cc + inter_cc
            return total_cc

    def dotpmm(self, mrow, mcol, m2row, m2col, mprec, overlap:int, inc_acc_prec=False):
        #overlap= number of columns per bram (aka 40xoverlap columns)
        numBRAM_for_cols = math.ceil(mcol / (self.bram.num_pes * overlap))
        numBRAM_for_rows = mrow
        numBRAM_required = numBRAM_for_rows*numBRAM_for_cols
        numMV_concurrent = max(1, math.floor(self.num_bram / numBRAM_required))
        numDotMV = math.ceil(m2col / numMV_concurrent)
        print_debug('num bram req: ' + str(numBRAM_required))
        print_debug('numMV conccurent: ' + str(numMV_concurrent))
        if(numBRAM_required > self.num_bram): #perform recursive call breaking apart dot product
            print_debug("splitting up dotpmv operation")
            #split up by rows as those are relatively independent
            rows_at_a_time = math.floor(self.num_bram / numBRAM_for_cols)
            full_dotp_runs = math.floor(mrow / rows_at_a_time) #cover all the "FULL" dot products. 
            print_debug('full dotp runs ' + str(full_dotp_runs))
            full_dotp_cc   = self.dotpmv(rows_at_a_time, mcol, m2row, mprec, overlap, inc_acc_prec)
            total_full_run_cc = full_dotp_cc*full_dotp_runs
            print_debug(total_full_run_cc)
            #cover the left-over "partial" dot product
            left_over_rows = mrow % rows_at_a_time
            left_over_run_cc = self.dotpmv(left_over_rows, mcol, m2row, mprec, overlap, inc_acc_prec)
            return (total_full_run_cc + left_over_run_cc)*numDotMV
        else: #perform dot product
            #perform regular MAC operations (overlap)
            num_macs = overlap
            print_debug('num macs: ' + str(num_macs))
            mult_cycles = self.bram.mult(self.base_prec, mprec)
            print_debug('mult cycles: ' + str(mult_cycles))
            total_mac_cycles = 0 #num_macs * mult_cycles
            print_debug('total mult cycles: ' + str(mult_cycles))
            
            acc_prec = mprec + self.base_prec + num_macs - 1
            
            #perform intra-BRAM accumulation
            acc_prec, intra_cc = self.intraAcc(min(self.bram.num_pes, mcol), acc_prec, inc_acc_prec=inc_acc_prec)
            
            #if needed, perform inter-BRAM accumulation
            inter_cc = 0
            if numBRAM_for_cols > 1:
                acc_prec, inter_cc = self.interAcc(numBRAM_for_cols, acc_prec, inc_acc_prec=inc_acc_prec)
                
            total_cc = total_mac_cycles + intra_cc + inter_cc
            total_cc *= numDotMV
            print_debug('num dotpmv: ' + str(numDotMV))
            return total_cc
    
    def dotpmv_explore(self, inrow, incol, in2row, inc_acc_prec=False):
        assert incol == in2row
        numBRAM_split = 1 #number of BRAMs that columns (dimension that is accumulated) are split between
        delays = []
        while (numBRAM_split) <= incol:
            # print_debug('\n\n')
            
            delay = self.dotpmv(inrow, incol, in2row, self.base_prec, numBRAM_split, inc_acc_prec=inc_acc_prec)
            delays.append(delay)
            numBRAM_split += 1
        print_debug(str(delays))
        return min(delays)
    
    def dotpmm_explore(self, inrow, incol, in2row, in2col, inc_acc_prec=False):
        assert incol == in2row
        numBRAM_split = 1 #number of BRAMs that columns (dimension that is accumulated) are split between
        delays = []
        while (numBRAM_split) <= 30:
            # print_debug('\n\n')
            print_debug(' ')
            delay = self.dotpmm(inrow, incol, in2row, in2col, self.base_prec, numBRAM_split, inc_acc_prec=inc_acc_prec)
            delays.append(delay)
            numBRAM_split += 1
        print_debug(str(delays))
        return min(delays)
    
class Im2Col():
    def calc_output_size(inh, inw, kh, kw, sh, sw, ph, pw):
        outw = 1 + ((inw - kw + 2*pw)/sw)
        outh = 1 + ((inh - kh + 2*ph)/sh)
        return outw, outh

    def conv_to_gemm(inh, inw, inc, kh, kw, num_filt, sh, sw, ph, pw):
        outw,outh = Im2Col.calc_output_size(inh, inw, kh, kw, sh, sw, ph, pw)
        outc = num_filt
        #work backwards to get outw x outh x outc matrix using dotpmm
        #(outc x _____) * (______ x outh*outw) = outc x (outh*outw)
        #each element in the output matrix is a kernel/filter activation
        #Each activation is a matrix-op with a kernel filter
        #each kernel filter is Kw*kh*inc
        kernel_dim = kw*kh*inc
        return outc, kernel_dim, kernel_dim, outw*outh

    def conv_out_to_gemm(kh, kw, inc, outh, outw, outc):
        kernel_dim = kw*kh*inc
        return outw*outh, kernel_dim, kernel_dim, outc
    
    
    
if __name__ == '__main__':
    fpga = PIM_FPGA(8, True, True)
    # print(fpga.dotpmv_explore(197, 738, 738, inc_acc_prec=True))
    print(fpga.dotpmm_explore(197, 738, 738, 64, inc_acc_prec=True))
    
    # print(fpga.dotpmv(197, 738, 738, fpga.base_prec, 2, inc_acc_prec=True))
    