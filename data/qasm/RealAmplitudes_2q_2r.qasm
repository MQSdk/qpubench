OPENQASM 3.0;
include "stdgates.inc";
input float[64] _θ_0_;
input float[64] _θ_1_;
input float[64] _θ_2_;
input float[64] _θ_3_;
input float[64] _θ_4_;
input float[64] _θ_5_;
qubit[2] q;
ry(_θ_0_) q[0];
ry(_θ_1_) q[1];
cx q[0], q[1];
ry(_θ_2_) q[0];
ry(_θ_3_) q[1];
cx q[0], q[1];
ry(_θ_4_) q[0];
ry(_θ_5_) q[1];

