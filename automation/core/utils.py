class TrieNode:
    def __init__(self):
        self.children = {}
        self.is_end = False
        self.contacts = []

class Trie:
    def __init__(self):
        self.root = TrieNode()

    def insert(self, contact, key):
        node = self.root
        for char in key.lower():
            if char not in node.children:
                node.children[char] = TrieNode()
            node = node.children[char]
            node.contacts.append(contact)  # 可選：只在葉節點存
        node.is_end = True

    def search_prefix(self, prefix):
        node = self.root
        for char in prefix.lower():
            if char not in node.children:
                return []
            node = node.children[char]
        return node.contacts