N = int(input())
A = [100,2,3,1,5,6]
B = [0,1,2,0,2,1]
C = [0] * N

#print("C =", C)

group0 = []
group1 = []
group2 = []
for i in range(N):
    ai = A[i]
    bi = B[i]
    if bi == 0:
        group0.append((ai, i))
    elif bi == 1:
        group1.append((ai, i))
    elif bi == 2:
        group2.append((ai, i))
count0, count1, count2 = len(group0), len(group1), len(group2)
#print(count0, count1, count2)


def make(group, start_val):
    group.sort()
    abs_diff = 0
    shift = 0
    for item in group:
        a_val,a_idx = item
        #print(a_val, a_idx)
        c_val = start_val + shift
        C[a_idx] = c_val
        abs_diff += abs(c_val - a_val)
        shift +=1
    return abs_diff

abs_diff_1 = make (group0, 1)
abs_diff_2 = make (group1, count0 + 1)
abs_diff_3 = make (group2, count0 + count1 + 1)

print("C =", C)
print("Total absolute difference =", abs_diff_1 + abs_diff_2 + abs_diff_3) 