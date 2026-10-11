//! Reproduces the real TLP spot-check (gate 128) in-process to bisect the
//! on-chain rejection: if this passes, the contract math is right and the
//! on-chain failure is transport; if it fails, the bug is in the contract.

use soroban_sdk::{testutils::Address as _, BytesN, Env, Vec};

#[test]
fn real_spot_check_math() {
    let env = Env::default();

    let k_l = hex16("276288749f4d3a873962574855efe6bf");
    let k_r = hex16("af4f40a8f947b4a88a1f0fcbe20bd88e");
    let k_o = hex16("d2ddbd85819a34241a8b8d68db4bb3d2");
    let ct00 = hex16("a3c668e7c11818ddea571813e34e61b5");
    let ct01 = hex16("9c339f0c5d5ba2d6f2c6bf3691e9d2ff");
    let ct10 = hex16("d883c5b819937af9a23bd9a8f8fa627a");
    let ct11 = hex16("a231d017e4ecfba031ca2b0a952969d2");
    let gi: u32 = 128;

    // Contract math: a*2+b selects the ciphertext.
    let a = (k_l.to_array()[0] & 1) as u32;
    let b = (k_r.to_array()[0] & 1) as u32;
    println!("a={} b={}", a, b);
    assert_eq!((a, b), (1, 1));

    let table = (ct00, ct01, ct10, ct11);
    let ct = match a * 2 + b {
        0 => &table.0,
        1 => &table.1,
        2 => &table.2,
        _ => &table.3,
    };
    println!("ct = {}", hex(ct.to_array()));

    // The pad, exactly as the contract computes it.
    let p = quantum_verifier::crypto_helpers::pad(&env, &k_l, &k_r, gi);
    println!("rust_pad = {}", hex(p.to_array()));
    println!("py_pad   = 70ec6d926576cf842b41a6624e62da00");

    // expected_k_o = ct ^ pad
    let expected = xor16(&env, ct, &p);
    println!("rust_xor = {}", hex(expected.to_array()));
    println!("k_o      = {}", hex(k_o.to_array()));

    assert_eq!(p.to_array(), hex16("70ec6d926576cf842b41a6624e62da00").to_array(),
        "RUST PAD != PYTHON PAD — pad() encoding bug confirmed");
    assert_eq!(expected, k_o, "spot-check math failed in-process");
}

fn hex16(s: &str) -> BytesN<16> {
    let mut out = [0u8; 16];
    for i in 0..16 {
        out[i] = u8::from_str_radix(&s[2 * i..2 * i + 2], 16).unwrap();
    }
    BytesN::<16>::from_array(&Env::default(), &out)
}

fn hex(b: [u8; 16]) -> String {
    b.iter().map(|x| format!("{:02x}", x)).collect()
}

fn xor16(env: &Env, a: &BytesN<16>, b: &BytesN<16>) -> BytesN<16> {
    let mut out = [0u8; 16];
    for i in 0..16 {
        out[i] = a.to_array()[i] ^ b.to_array()[i];
    }
    BytesN::<16>::from_array(env, &out)
}
