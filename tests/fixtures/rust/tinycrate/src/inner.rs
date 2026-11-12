//! Private things, re-exported at the root.

/// A token of text.
pub struct Token(pub String);

pub mod helpers {
    use super::Token;

    /// Count the tokens.
    pub fn count(tokens: &[Token],  // the tokens
    ) -> usize {  // how many there are
        tokens.len()
    }
}
