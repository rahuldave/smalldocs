//! Paths as the source writes them, values that rustdoc gives as `_`, and `# Returns`.

use std::io;
use std::path::Path;

/// The result of this module, which is not its own `Result`.
pub type Result<T> = std::result::Result<T, Error>;

/// An error.
pub enum Error {
    /// A file failed.
    Io(io::Error),
}

/// The names, which rustdoc gives as `_`.
pub const NAMES: [&str; 2] = [
    "a",  // the first
    "b",
];

/// Read a file.
///
/// # Returns
///
/// The text of the file.
pub fn read(path: &Path,  // the file
) -> Result<String> {
    std::fs::read_to_string(path).map_err(Error::Io)
}

/// Read a file, with no word on what it gives back.
pub fn read_quietly(path: &Path,  // the file
) -> Result<String> {
    read(path)
}
