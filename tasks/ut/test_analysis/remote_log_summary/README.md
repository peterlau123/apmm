
当前文件夹中用于存放远程机器**ut_logs**下单元测试日志统计输出的文件

+ failed_xxx_<时间按戳> 代表指定日期统计的失败的单元测试列表
+ error_xxx_<时间戳> 代表指定日期统计的发生错误的单元测试列表
+ passed_xxx_<时间戳> 代表指定日期统计发生的通过的单元测试列表


它们生成的命令如下


```bash

grep -E "PASSED" -Rn ut_logs/*.log |  grep -v -E "tpu|_tpu_|_mm_|multi_modal|whisper" >passed_ut_cases-20260606.txt

grep -E "ERROR" -Rn ut_logs/*.log |  grep -v -E "tpu|_tpu_|_mm_|multi_modal|whisper" > error_ut_cases-20260606.txt


grep -E "FAILED" -Rn ut_logs/*.log |  grep -v -E "tpu|_tpu_|_mm_|multi_modal|whisper" > failed_ut_cases-20260606.txt


```


后续agent也可以定期全照上述方式统计ut_logs，获取最新的测试统计信息并将统计文件放于当前文件夹内
