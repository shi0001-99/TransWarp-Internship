# 第09章 Kmeans代码实现

> 对应视频：第68-73讲

---

## 视频68：Kmeans算法模块概述（第九章：Kmeans代码实现 1）

### 知识点
- **K-Means代码结构**：
  ```
  KMeans类
  ├── __init__(n_clusters, max_iter, tol)  # 初始化
  ├── _init_centroids(X)                   # 初始化簇中心
  ├── _assign_clusters(X, centroids)       # 分配样本
  ├── _update_centroids(X, labels)         # 更新中心
  ├── fit(X)                               # 训练
  ├── predict(X)                           # 预测
  └── _compute_distance(x1, x2)            # 距离计算
  ```
- **距离度量**：欧氏距离 $d(x_1, x_2) = \sqrt{\sum(x_{1i} - x_{2i})^2}$

---

## 视频69：计算得到簇中心点（2）

### 知识点
- **簇中心初始化方法**：
  - 随机初始化：从数据中随机选K个点
  - K-Means++：
    1. 随机选第一个中心
    2. 计算每个点到已有中心的距离
    3. 按距离平方概率选择下一个中心
    4. 重复直至选够K个
- **K-Means++的优势**：更稳定的收敛，避免局部最优
- **代码实现**：
  ```python
  def _init_centroids(self, X):
      idx = np.random.choice(n_samples, self.n_clusters, replace=False)
      return X[idx]
  ```

---

## 视频70：样本点归属划分（3）

### 知识点
- **样本分配逻辑**：
  ```python
  def _assign_clusters(self, X, centroids):
      distances = np.linalg.norm(X[:, np.newaxis] - centroids, axis=2)
      return np.argmin(distances, axis=1)
  ```
- **向量化计算**：使用NumPy广播机制高效计算距离
- **处理维度**：确保输入为2D数组

---

## 视频71：算法迭代更新（4）

### 知识点
- **迭代更新步骤**：
  ```python
  for i in range(max_iter):
      # 分配样本
      labels = self._assign_clusters(X, centroids)
      # 更新中心
      new_centroids = np.array([X[labels == k].mean(axis=0) 
                                 for k in range(self.n_clusters)])
      # 检查收敛
      if np.allclose(centroids, new_centroids):
          break
      centroids = new_centroids
  ```
- **收敛判断**：新旧中心差异小于阈值

---

## 视频72：鸢尾花数据集聚类任务（5）

### 知识点
- **加载数据**：
  ```python
  from sklearn.datasets import load_iris
  iris = load_iris()
  X = iris.data[:, :2]  # 取前两个特征便于可视化
  ```
- **训练模型**：
  ```python
  from sklearn.cluster import KMeans
  kmeans = KMeans(n_clusters=3, random_state=42)
  kmeans.fit(X)
  ```
- **预测与评估**：与真实标签对比（虽然聚类不使用标签）

---

## 视频73：聚类效果展示（6）

### 知识点
- **聚类结果可视化**：
  ```python
  plt.scatter(X[:, 0], X[:, 1], c=labels, cmap='viridis')
  plt.scatter(centroids[:, 0], centroids[:, 1], 
              marker='x', s=200, linewidths=3, color='red')
  ```
- **聚类效果评估**：
  - 轮廓系数（Silhouette Score）
  - Davies-Bouldin指数
  - Calinski-Harabasz指数
- **K值选择**：肘部法则（Elbow Method）
