# 第25章 代码实现word2vec词向量模型

> 对应视频：第191-195讲

---

## 视频191：数据与任务流程（第二十五章：代码实现word2vec词向量模型 1）

### 知识点
- **Word2Vec实现流程**：
  ```
  1. 数据收集与预处理
  2. 分词与词表构建
  3. 生成训练样本
  4. 构建神经网络模型
  5. 训练模型
  6. 提取词向量
  7. 可视化与应用
  ```
- **使用库选择**：
  - 使用`gensim`库（推荐）
  - 或使用`PyTorch`/`TensorFlow`手写实现

---

## 视频192：数据清洗（2）

### 知识点
- **文本数据预处理**：
  ```python
  import jieba  # 中文分词
  
  def preprocess(texts):
      # 1. 分词
      tokenized = [jieba.lcut(text) for text in texts]
      
      # 2. 去除停用词
      stopwords = set(open('stopwords.txt').read().split())
      cleaned = [[w for w in sent if w not in stopwords 
                  and len(w) > 1] for sent in tokenized]
      
      # 3. 构建词表
      vocab = {}
      for sent in cleaned:
          for word in sent:
              if word not in vocab:
                  vocab[word] = len(vocab)
      
      return cleaned, vocab
  ```
- **中文分词工具**：
  - jieba分词
  - THULAC
  - pkuseg

---

## 视频193：batch数据制作（3）

### 知识点
- **生成训练样本（Skip-gram）**：
  ```python
  def generate_samples(sentences, window_size):
      samples = []
      for sentence in sentences:
          for i, center_word in enumerate(sentence):
              # 获取上下文词
              start = max(0, i - window_size)
              end = min(len(sentence), i + window_size + 1)
              
              for j in range(start, end):
                  if j != i:
                      context_word = sentence[j]
                      samples.append((center_word, context_word))
      
      return samples
  ```
- **Batch数据生成**：
  ```python
  def get_batch(samples, batch_size):
      indices = np.random.choice(len(samples), batch_size, replace=False)
      batch = [samples[i] for i in indices]
      
      # 转换为索引
      center_idx = [vocab[sample[0]] for sample in batch]
      context_idx = [vocab[sample[1]] for sample in batch]
      
      return center_idx, context_idx
  ```

---

## 视频194：网络训练（4）

### 知识点
- **使用gensim训练Word2Vec**：
  ```python
  from gensim.models import Word2Vec
  
  # 训练Word2Vec模型
  model = Word2Vec(
      sentences=sentences,           # 分词后的句子列表
      vector_size=100,                # 词向量维度
      window=5,                       # 上下文窗口大小
      min_count=2,                    # 最小词频
      sg=1,                           # 1=Skip-gram, 0=CBOW
      workers=4,                      # 并行线程数
      epochs=50                       # 训练轮数
  )
  ```
- **模型训练过程**：
  ```python
  # 自定义训练过程（PyTorch实现）
  for epoch in range(epochs):
      total_loss = 0
      for batch in dataloader:
          # 前向传播
          center_emb = embedding(center_idx)       # (batch, dim)
          context_emb = embedding(context_idx)     # (batch, dim)
          
          # 计算相似度
          score = torch.sum(center_emb * context_emb, dim=1)
          
          # 负采样
          neg_emb = embedding(neg_idx)              # (batch, k, dim)
          neg_score = torch.bmm(neg_emb, center_emb.unsqueeze(2)).squeeze()
          
          # 计算损失
          loss = -torch.mean(F.logsigmoid(score) + 
                            torch.sum(F.logsigmoid(-neg_score), dim=1))
          
          # 反向传播
          optimizer.zero_grad()
          loss.backward()
          optimizer.step()
          
          total_loss += loss.item()
      
      print(f'Epoch {epoch}: Loss = {total_loss:.4f}')
  ```

---

## 视频195：可视化展示（5）

### 知识点
- **词向量提取**：
  ```python
  # gensim方式
  vector = model.wv['学习']  # 获取"学习"的词向量
  similar_words = model.wv.most_similar('学习', topn=10)  # 找相似词
  
  # 词向量运算
  # 国王 - 男人 + 女人 ≈ 女王
  result = model.wv.most_similar(positive=['国王', '女人'], 
                                  negative=['男人'], topn=1)
  ```
- **降维可视化（t-SNE）**：
  ```python
  from sklearn.manifold import TSNE
  import matplotlib.pyplot as plt
  
  # 取部分词向量
  words = list(model.wv.vocab.keys())[:100]
  vectors = [model.wv[word] for word in words]
  
  # t-SNE降维
  tsne = TSNE(n_components=2, random_state=42)
  vectors_2d = tsne.fit_transform(vectors)
  
  # 可视化
  plt.figure(figsize=(10, 8))
  for i, word in enumerate(words):
      x, y = vectors_2d[i]
      plt.scatter(x, y)
      plt.annotate(word, (x, y), fontsize=8)
  plt.show()
  ```
- **词向量应用**：
  - 文本相似度计算
  - 文档分类
  - 推荐系统
  - 机器翻译
  - 对话系统
