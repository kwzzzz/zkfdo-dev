use std::{fs, path::Path};

use anyhow::{ensure, Context, Result};
use num_bigint::BigUint;

/// Reads a circom/snarkjs `.wtns` file (version 2) and returns the wire values.
pub(crate) fn read_wtns(path: &Path, prime: &BigUint) -> Result<Vec<BigUint>> {
    let bytes = fs::read(path).with_context(|| format!("read witness {}", path.display()))?;
    parse_wtns(&bytes, prime).with_context(|| format!("parse witness {}", path.display()))
}

pub(crate) fn parse_wtns(bytes: &[u8], prime: &BigUint) -> Result<Vec<BigUint>> {
    let mut cursor = Cursor { bytes, offset: 0 };
    ensure!(cursor.take(4)? == b"wtns", "invalid wtns magic");
    ensure!(cursor.u32()? == 2, "unsupported wtns version");
    ensure!(cursor.u32()? == 2, "wtns must contain exactly two sections");

    let mut header = None;
    let mut data = None;
    for _ in 0..2 {
        let kind = cursor.u32()?;
        let length = usize::try_from(cursor.u64()?).context("wtns section length")?;
        let section = cursor.take(length)?;
        match kind {
            1 => header = Some(section),
            2 => data = Some(section),
            other => anyhow::bail!("unexpected wtns section {other}"),
        }
    }
    ensure!(
        cursor.offset == bytes.len(),
        "trailing bytes after wtns sections"
    );
    let mut header = Cursor {
        bytes: header.context("wtns header section missing")?,
        offset: 0,
    };
    let field_bytes = usize::try_from(header.u32()?).context("wtns field size")?;
    ensure!(field_bytes > 0, "wtns field size must be positive");
    let file_prime = BigUint::from_bytes_le(header.take(field_bytes)?);
    ensure!(
        &file_prime == prime,
        "wtns prime differs from the R1CS prime"
    );
    let count = usize::try_from(header.u32()?).context("wtns witness count")?;
    let data = data.context("wtns data section missing")?;
    ensure!(
        data.len() == count * field_bytes,
        "wtns data length does not match its witness count"
    );
    let values = data
        .chunks(field_bytes)
        .map(BigUint::from_bytes_le)
        .collect::<Vec<_>>();
    for (wire, value) in values.iter().enumerate() {
        ensure!(value < prime, "wtns wire {wire} is not canonical");
    }
    Ok(values)
}

#[cfg(test)]
pub(crate) fn write_wtns(path: &Path, prime: &BigUint, values: &[BigUint]) -> Result<()> {
    let field_bytes = prime.to_bytes_le().len().div_ceil(8) * 8;
    let mut header = Vec::new();
    header.extend_from_slice(&(field_bytes as u32).to_le_bytes());
    header.extend_from_slice(&padded(prime, field_bytes)?);
    header.extend_from_slice(&(values.len() as u32).to_le_bytes());
    let mut data = Vec::with_capacity(values.len() * field_bytes);
    for value in values {
        ensure!(value < prime, "witness value is not canonical");
        data.extend_from_slice(&padded(value, field_bytes)?);
    }

    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"wtns");
    bytes.extend_from_slice(&2u32.to_le_bytes());
    bytes.extend_from_slice(&2u32.to_le_bytes());
    for (kind, section) in [(1u32, &header), (2u32, &data)] {
        bytes.extend_from_slice(&kind.to_le_bytes());
        bytes.extend_from_slice(&(section.len() as u64).to_le_bytes());
        bytes.extend_from_slice(section);
    }
    fs::write(path, bytes).with_context(|| format!("write witness {}", path.display()))
}

#[cfg(test)]
fn padded(value: &BigUint, width: usize) -> Result<Vec<u8>> {
    let mut bytes = value.to_bytes_le();
    ensure!(bytes.len() <= width, "field element exceeds wtns width");
    bytes.resize(width, 0);
    Ok(bytes)
}

struct Cursor<'a> {
    bytes: &'a [u8],
    offset: usize,
}

impl<'a> Cursor<'a> {
    fn take(&mut self, length: usize) -> Result<&'a [u8]> {
        let end = self
            .offset
            .checked_add(length)
            .context("wtns offset overflow")?;
        ensure!(end <= self.bytes.len(), "truncated wtns file");
        let slice = &self.bytes[self.offset..end];
        self.offset = end;
        Ok(slice)
    }

    fn u32(&mut self) -> Result<u32> {
        Ok(u32::from_le_bytes(self.take(4)?.try_into()?))
    }

    fn u64(&mut self) -> Result<u64> {
        Ok(u64::from_le_bytes(self.take(8)?.try_into()?))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn wtns_round_trip_preserves_values() {
        let prime = BigUint::from(97u32);
        let values = vec![
            BigUint::from(1u32),
            BigUint::from(42u32),
            BigUint::from(0u32),
        ];
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("w.wtns");
        write_wtns(&path, &prime, &values).unwrap();
        assert_eq!(read_wtns(&path, &prime).unwrap(), values);
        assert!(read_wtns(&path, &BigUint::from(101u32)).is_err());
    }
}
